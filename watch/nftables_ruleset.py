from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
CIDR_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}/\d{1,2}\b")


@dataclass(frozen=True)
class NftChain:
    name: str
    rules: tuple[str, ...]


@dataclass(frozen=True)
class NftSet:
    name: str
    ips: tuple[str, ...]
    cidrs: tuple[str, ...]


@dataclass(frozen=True)
class NftRuleset:
    path: Path
    sets: tuple[NftSet, ...]
    chains: tuple[NftChain, ...]
    referenced_sets: tuple[str, ...] = field(default_factory=tuple)


def parse_nftables_ruleset(path: Path) -> NftRuleset:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    sets: dict[str, dict[str, list[str]]] = {}
    current_set: str | None = None
    set_indent: int | None = None
    in_elements = False
    element_buf: list[str] = []

    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        set_match = re.match(r"^\s*set (\w+) \{", line)
        if set_match:
            current_set = set_match.group(1)
            set_indent = indent
            sets[current_set] = {"ips": [], "cidrs": []}
            in_elements = False
            element_buf = []
            continue

        if current_set is None:
            continue

        if stripped == "}" and set_indent is not None and indent <= set_indent:
            if in_elements and element_buf:
                _append_elements(sets[current_set], "".join(element_buf))
            current_set = None
            set_indent = None
            in_elements = False
            element_buf = []
            continue

        if "elements" in line:
            in_elements = True
            element_buf = [line.split("=", 1)[-1]]
            if line.rstrip().endswith("}"):
                _append_elements(sets[current_set], "".join(element_buf))
                in_elements = False
                element_buf = []
            continue

        if in_elements:
            element_buf.append(line)
            if line.rstrip().endswith("}"):
                _append_elements(sets[current_set], "".join(element_buf))
                in_elements = False
                element_buf = []

    chains: list[NftChain] = []
    for match in re.finditer(
        r"chain (\w+) \{([^}]+)\}",
        text,
        re.DOTALL,
    ):
        name = match.group(1)
        body = match.group(2)
        rules = tuple(
            stripped
            for raw in body.splitlines()
            if (stripped := raw.strip())
            and not stripped.startswith("type ")
        )
        chains.append(NftChain(name=name, rules=rules))

    referenced = tuple(sorted(set(re.findall(r"@(\w+)", text))))

    return NftRuleset(
        path=path,
        sets=tuple(
            NftSet(
                name=name,
                ips=tuple(data["ips"]),
                cidrs=tuple(data["cidrs"]),
            )
            for name, data in sorted(sets.items())
        ),
        chains=tuple(chains),
        referenced_sets=referenced,
    )


def _append_elements(bucket: dict[str, list[str]], body: str) -> None:
    bucket["ips"].extend(IP_RE.findall(body))
    bucket["cidrs"].extend(CIDR_RE.findall(body))


def all_ips_from_ruleset(ruleset: NftRuleset) -> list[str]:
    ips: list[str] = []
    for nft_set in ruleset.sets:
        ips.extend(nft_set.ips)
    return ips
