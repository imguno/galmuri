"""Typed linear document processing, independent of transport and source providers."""

from galmuri.processing.defaults import process_default
from galmuri.processing.pipeline import Pipeline
from galmuri.processing.steps import Step

__all__ = ["Pipeline", "Step", "process_default"]
