from pathlib import Path

from watch.nftables_ruleset import parse_nftables_ruleset


def test_parse_nftables_ruleset_extracts_sets(tmp_path: Path):
  rules = tmp_path / "rules.nft"
  rules.write_text(
    """
table inet filter {
    set bots2 {
        type ipv4_addr
        elements = { 1.2.3.4, 5.6.7.8 }
    }
    set empty_set {
        type ipv4_addr
    }
    chain input {
        type filter hook input priority 0; policy accept;
        ip saddr @bots2 drop
    }
}
""".strip(),
    encoding="utf-8",
  )

  parsed = parse_nftables_ruleset(rules)
  assert len(parsed.sets) == 2
  bots = next(s for s in parsed.sets if s.name == "bots2")
  assert bots.ips == ("1.2.3.4", "5.6.7.8")
  assert parsed.referenced_sets == ("bots2",)


def test_collapse_host_ips_handles_large_lists():
    from watch.subnet import collapse_host_ips

    ips = [f"10.0.{prefix // 256}.{prefix % 256}" for prefix in range(512)]
    collapsed = collapse_host_ips(ips)
    assert collapsed
    assert len(collapsed) < len(ips)
