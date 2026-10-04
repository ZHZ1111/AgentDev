"""F2 versioned, handwritten fixtures; public task inputs exclude evaluation oracles."""

from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from .models import ContractModel, Identifier, SourceInfo, Text
from .tools import analyze_source


DEFAULT_DATASET = Path(__file__).resolve().parents[2] / "benchmarks/f2/v1"
Category = Literal["numeric_boundaries", "strings", "lists", "exceptions_branches"]


class BenchmarkCase(ContractModel):
    case_id: Identifier
    split: Literal["development", "holdout"]
    source: Text
    specification: Text
    oracles: Text
    annotations: Text
    functions: dict[Identifier, Category]


class KnownVariant(ContractModel):
    variant_id: Identifier
    case_id: Identifier
    affected_function: Identifier
    source: Text
    kind: Literal["boundary", "data_flow", "normalization", "empty_branch"]
    description: Text
    witnesses: tuple[Identifier, ...] = Field(min_length=1)
    failure_types: tuple[Text, ...] = Field(min_length=1)


class DatasetManifest(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: Literal["f2-v1"] = "f2-v1"
    provenance: Text
    holdout_policy: Text
    cases: tuple[BenchmarkCase, ...]
    variants: tuple[KnownVariant, ...]
    sha256: dict[str, str]

    @model_validator(mode="after")
    def consistent(self):
        ids = [case.case_id for case in self.cases]
        variants = [item.variant_id for item in self.variants]
        if len(ids) != len(set(ids)) or len(variants) != len(set(variants)):
            raise ValueError("duplicate case/variant identifiers")
        counts = Counter(category for case in self.cases for category in case.functions.values())
        if counts != dict.fromkeys(("numeric_boundaries", "strings", "lists", "exceptions_branches"), 3):
            raise ValueError("F2 v1 requires twelve functions, three in each category")
        if sum(len(case.functions) for case in self.cases if case.split == "holdout") != 4:
            raise ValueError("F2 v1 reserves four holdout functions")
        lookup = {case.case_id: case for case in self.cases}
        if len(self.variants) != 6 or len({item.affected_function for item in self.variants}) != 6:
            raise ValueError("F2 v1 requires six affected functions and six variants")
        for item in self.variants:
            if item.case_id not in lookup or item.affected_function not in lookup[item.case_id].functions:
                raise ValueError("variant must affect a known function in its case")
        paths = {path for case in self.cases for path in (case.source, case.specification, case.oracles, case.annotations)}
        paths.update(item.source for item in self.variants)
        if set(self.sha256) != paths or any(len(value) != 64 or any(c not in "0123456789abcdef" for c in value) for value in self.sha256.values()):
            raise ValueError("every fixture requires an explicit SHA256 fingerprint")
        return self


class OracleExpectation(ContractModel):
    kind: Literal["returns", "raises"]
    value: JsonValue = None
    exception: Literal["ValueError", "TypeError"] | None = None
    python_type: Literal["int", "float", "str", "list"] | None = None
    fresh_result: bool = False

    @model_validator(mode="after")
    def consistent(self):
        if self.kind == "raises" and (not self.exception or self.value is not None or self.python_type or self.fresh_result):
            raise ValueError("exception oracle needs only an exception type")
        if self.kind == "returns" and (self.exception or not self.python_type):
            raise ValueError("return oracle needs a declared Python type")
        return self


class OracleScenario(ContractModel):
    scenario_id: Identifier
    function: Identifier
    args: tuple[JsonValue, ...]
    kwargs: dict[Identifier, JsonValue]
    expectation: OracleExpectation
    test_kind: Literal["unit", "collaboration"]


class OracleSet(ContractModel):
    provenance: Text
    scenarios: tuple[OracleScenario, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self):
        if len({item.scenario_id for item in self.scenarios}) != len(self.scenarios):
            raise ValueError("duplicate oracle identifiers")
        return self


class AnnotatedEdge(ContractModel):
    caller: Identifier
    callee: Identifier
    line: int = Field(ge=1)
    expression: Text


class CombinedBehavior(ContractModel):
    description: Text
    scenario_ids: tuple[Identifier, ...] = Field(min_length=1)


class CaseAnnotations(ContractModel):
    provenance: Text
    confirmed_edges: tuple[AnnotatedEdge, ...]
    reasonable_entries: tuple[Identifier, ...] = Field(min_length=1)
    combined_behaviors: tuple[CombinedBehavior, ...]
    independent_control: bool


class PublicCaseInput(ContractModel):
    """Only source facts and behavior specification may enter the model context."""
    source: SourceInfo
    behavior_specification: Text


class BenchmarkDataset:
    def __init__(self, root: Path = DEFAULT_DATASET):
        self.root = root.resolve()
        self.manifest = DatasetManifest.model_validate_json((self.root / "manifest.json").read_text(encoding="utf-8"))
        for relative, expected in self.manifest.sha256.items():
            if hashlib.sha256(self.path(relative).read_bytes()).hexdigest() != expected:
                raise ValueError(f"fixture fingerprint mismatch: {relative}")

    def path(self, relative: str) -> Path:
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative:
            raise ValueError("fixture path must stay within the dataset")
        target = self.root.joinpath(*path.parts).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("fixture path escapes the dataset")
        return target

    def case(self, case_id: str) -> BenchmarkCase:
        for item in self.manifest.cases:
            if item.case_id == case_id:
                return item
        raise KeyError(case_id)

    def public_input(self, case_id: str) -> PublicCaseInput:
        case = self.case(case_id)
        return PublicCaseInput(source=analyze_source(self.path(case.source)),
                               behavior_specification=self.path(case.specification).read_text(encoding="utf-8"))

    def oracles(self, case_id: str) -> OracleSet:
        case = self.case(case_id)
        result = OracleSet.model_validate_json(self.path(case.oracles).read_text(encoding="utf-8"))
        if {item.function for item in result.scenarios} != set(case.functions):
            raise ValueError("oracle targets must cover exactly the case functions")
        return result

    def annotations(self, case_id: str) -> CaseAnnotations:
        return CaseAnnotations.model_validate_json(self.path(self.case(case_id).annotations).read_text(encoding="utf-8"))


def handwritten_tests(oracles: OracleSet) -> str:
    """Render literal human expectations, never derive expected results from source."""
    functions = sorted({item.function for item in oracles.scenarios})
    lines = ["# Handwritten F2 oracle materialization; not model-generated.",
             "import pytest", "from copy import deepcopy", "from subject import " + ", ".join(functions), ""]
    for item in oracles.scenarios:
        lines.extend([f"def test_{item.scenario_id}():", f"    args = {list(item.args)!r}",
                      f"    kwargs = {item.kwargs!r}", "    before = deepcopy((args, kwargs))"])
        call = f"{item.function}(*args, **kwargs)"
        expected = item.expectation
        if expected.kind == "raises":
            lines.extend([f"    with pytest.raises({expected.exception}):", f"        {call}"])
        else:
            lines.extend([f"    actual = {call}", f"    assert actual == {expected.value!r}",
                          f"    assert type(actual) is {expected.python_type}"])
            if expected.fresh_result:
                lines.append("    assert all(actual is not value for value in args if isinstance(value, list))")
        lines.extend(["    assert (args, kwargs) == before", ""])
    return "\n".join(lines)
