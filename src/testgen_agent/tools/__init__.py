"""Bounded source analysis and (in stage D) test execution tools."""

from .code_analyzer import (
    DataFlowHint,
    SourceAnalysisError,
    UnsupportedSourceError,
    analyze_loaded_source,
    analyze_source,
    build_call_graph,
    candidate_entry_functions,
    find_explicit_data_flows,
    find_call_cycles,
)
from .source_reader import LoadedSource, MAX_SOURCE_BYTES, SourceReadError, read_source

__all__ = [
    "LoadedSource",
    "MAX_SOURCE_BYTES",
    "SourceAnalysisError",
    "SourceReadError",
    "UnsupportedSourceError",
    "DataFlowHint",
    "analyze_loaded_source",
    "analyze_source",
    "build_call_graph",
    "candidate_entry_functions",
    "find_explicit_data_flows",
    "find_call_cycles",
    "read_source",
]
