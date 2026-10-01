"""Model factories that mirror the paper v1 training configurations.

Each factory returns an object with ``fit(frame, y)`` and ``score(frame)``.
The hyperparameters are read from the same YAML files the paper used so
that a re-analysis differs from the published run only in the split.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd
import yaml

from crackedpdfs_reanalysis import detector  # noqa: F401  (adds the frozen detector to sys.path)
from crackedpdfs_reanalysis.sanitizer import build_preprocessing, sanitize

from src.features.normalize import (
    build_logreg_preprocessor,
    build_tree_preprocessor,
    ordered_feature_frame,
    select_feature_columns,
)
from src.models.train_hybrid import TEXT_COLUMN
from src.models.train_hybrid import _build_pipeline as build_hybrid_pipeline
from src.models.train_text import _build_pipeline as build_text_pipeline


class Scorer(Protocol):
    def fit(self, frame: pd.DataFrame, y: np.ndarray) -> Scorer: ...

    def score(self, frame: pd.DataFrame) -> np.ndarray: ...


def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def sanitized_text(raw_text: pd.Series, text_cfg: dict[str, Any]) -> pd.Series:
    preprocessing = build_preprocessing(text_cfg)
    return raw_text.fillna("").astype(str).map(lambda text: sanitize(text, preprocessing))


class HybridScorer:
    """Sanitized text TF-IDF plus shortcut-free numeric features, logistic regression."""

    def __init__(self, config: dict[str, Any], text_column: str) -> None:
        self.config = config
        self.text_column = text_column
        self.feature_columns = select_feature_columns(
            list(config.get("drop_feature_groups", []) or []),
            list(config.get("drop_feature_columns", []) or []),
        )
        self.pipeline = None

    def _pipeline(self):
        cfg = self.config["text_tfidf"]
        hybrid = self.config.get("hybrid", {})
        return build_hybrid_pipeline(
            feature_columns=self.feature_columns,
            c_value=float(hybrid.get("c_values", [1.0])[0]),
            max_iter=int(hybrid.get("max_iter", 4000)),
            class_weight=hybrid.get("class_weight"),
            solver=str(hybrid.get("solver", "liblinear")),
            word_ngram_range=tuple(cfg["word_ngram_range"]),
            char_ngram_range=tuple(cfg["char_ngram_range"]),
            max_features_word=int(cfg["max_features_word"]),
            max_features_char=int(cfg["max_features_char"]),
            min_df=int(cfg["min_df"]),
            max_df=float(cfg["max_df"]),
        )

    def _frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        numeric = ordered_feature_frame(frame, self.feature_columns)
        numeric[TEXT_COLUMN] = frame[self.text_column].astype(str).to_numpy()
        return numeric

    def fit(self, frame: pd.DataFrame, y: np.ndarray) -> HybridScorer:
        self.pipeline = self._pipeline().fit(self._frame(frame), y)
        return self

    def score(self, frame: pd.DataFrame) -> np.ndarray:
        assert self.pipeline is not None
        return self.pipeline.predict_proba(self._frame(frame))[:, 1]

    def top_weights(self, limit: int = 25) -> dict[str, list[tuple[str, float]]]:
        assert self.pipeline is not None
        names = self.pipeline.named_steps["features"].get_feature_names_out()
        weights = self.pipeline.named_steps["classifier"].coef_[0]
        order = np.argsort(weights)
        positive = [(str(names[i]), float(weights[i])) for i in order[::-1][:limit]]
        negative = [(str(names[i]), float(weights[i])) for i in order[:limit]]
        return {"top_positive": positive, "top_negative": negative}


class TextScorer:
    """Sanitized text TF-IDF only, logistic regression."""

    def __init__(self, config: dict[str, Any], text_column: str) -> None:
        self.config = config
        self.text_column = text_column
        self.pipeline = None

    def _pipeline(self):
        cfg = self.config["text_tfidf"]
        return build_text_pipeline(
            c_value=float(cfg.get("c_values", [1.0])[0]),
            max_iter=int(cfg.get("max_iter", 4000)),
            class_weight=cfg.get("class_weight"),
            solver=str(cfg.get("solver", "liblinear")),
            word_ngram_range=tuple(cfg["word_ngram_range"]),
            char_ngram_range=tuple(cfg["char_ngram_range"]),
            max_features_word=int(cfg["max_features_word"]),
            max_features_char=int(cfg["max_features_char"]),
            min_df=int(cfg["min_df"]),
            max_df=float(cfg["max_df"]),
        )

    def fit(self, frame: pd.DataFrame, y: np.ndarray) -> TextScorer:
        self.pipeline = self._pipeline().fit(frame[self.text_column].astype(str).tolist(), y)
        return self

    def score(self, frame: pd.DataFrame) -> np.ndarray:
        assert self.pipeline is not None
        return self.pipeline.predict_proba(frame[self.text_column].astype(str).tolist())[:, 1]

    def top_weights(self, limit: int = 25) -> dict[str, list[tuple[str, float]]]:
        assert self.pipeline is not None
        names = self.pipeline.named_steps["features"].get_feature_names_out()
        weights = self.pipeline.named_steps["classifier"].coef_[0]
        order = np.argsort(weights)
        positive = [(str(names[i]), float(weights[i])) for i in order[::-1][:limit]]
        negative = [(str(names[i]), float(weights[i])) for i in order[:limit]]
        return {"top_positive": positive, "top_negative": negative}


class LogRegScorer:
    """Shortcut-free structural logistic regression. C is chosen on validation by the caller."""

    def __init__(self, config: dict[str, Any], c_value: float) -> None:
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline

        self.feature_columns = select_feature_columns(
            list(config.get("drop_feature_groups", []) or []),
            list(config.get("drop_feature_columns", []) or []),
        )
        cfg = config.get("logreg", {})
        self.pipeline = Pipeline(
            steps=[
                ("preprocessor", build_logreg_preprocessor()),
                (
                    "classifier",
                    LogisticRegression(
                        C=c_value,
                        max_iter=int(cfg.get("max_iter", 4000)),
                        class_weight=cfg.get("class_weight"),
                        solver=str(cfg.get("solver", "liblinear")),
                    ),
                ),
            ]
        )

    def fit(self, frame: pd.DataFrame, y: np.ndarray) -> LogRegScorer:
        self.pipeline.fit(ordered_feature_frame(frame, self.feature_columns), y)
        return self

    def score(self, frame: pd.DataFrame) -> np.ndarray:
        return self.pipeline.predict_proba(ordered_feature_frame(frame, self.feature_columns))[:, 1]


class XgbScorer:
    """Shortcut-free structural XGBoost with early stopping on the validation slice."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.feature_columns = select_feature_columns(
            list(config.get("drop_feature_groups", []) or []),
            list(config.get("drop_feature_columns", []) or []),
        )
        cfg = config.get("xgb", {})
        self.kwargs = {
            "n_estimators": int(cfg.get("n_estimators", 400)),
            "max_depth": int(cfg.get("max_depth", 4)),
            "learning_rate": float(cfg.get("learning_rate", 0.05)),
            "subsample": float(cfg.get("subsample", 0.9)),
            "colsample_bytree": float(cfg.get("colsample_bytree", 0.9)),
            "reg_lambda": float(cfg.get("reg_lambda", 1.0)),
            "min_child_weight": float(cfg.get("min_child_weight", 1.0)),
            "random_state": int(config.get("random_state", 42)),
            "objective": "binary:logistic",
            "eval_metric": str(cfg.get("eval_metric", "logloss")),
        }
        self.early_stopping_rounds = int(cfg.get("early_stopping_rounds", 25))
        self.preprocessor = build_tree_preprocessor()
        self.model = None
        self.n_estimators: int | None = None

    def warm_fit(
        self, frame: pd.DataFrame, y: np.ndarray, val_frame: pd.DataFrame, y_val: np.ndarray
    ) -> XgbScorer:
        from xgboost import XGBClassifier

        x = self.preprocessor.fit_transform(ordered_feature_frame(frame, self.feature_columns))
        x_val = self.preprocessor.transform(ordered_feature_frame(val_frame, self.feature_columns))
        model = XGBClassifier(**self.kwargs, early_stopping_rounds=self.early_stopping_rounds)
        model.fit(x, y, eval_set=[(x_val, y_val)], verbose=False)
        best = getattr(model, "best_iteration", None)
        self.n_estimators = self.kwargs["n_estimators"] if best is None else max(1, int(best) + 1)
        self.model = model
        return self

    def fit(self, frame: pd.DataFrame, y: np.ndarray) -> XgbScorer:
        from xgboost import XGBClassifier

        x = self.preprocessor.fit_transform(ordered_feature_frame(frame, self.feature_columns))
        self.model = XGBClassifier(
            **{**self.kwargs, "n_estimators": self.n_estimators or self.kwargs["n_estimators"]}
        )
        self.model.fit(x, y, verbose=False)
        return self

    def score(self, frame: pd.DataFrame) -> np.ndarray:
        assert self.model is not None
        return self.model.predict_proba(
            self.preprocessor.transform(ordered_feature_frame(frame, self.feature_columns))
        )[:, 1]
