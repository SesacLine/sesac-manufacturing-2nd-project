"""스텝 3 이후 로직이 채워지기 전까지의 최소 골격 — import가 깨지지 않는지만 확인한다."""
from backend import graph, state


def test_rca_state_importable():
    assert hasattr(state, "RCAState")


def test_build_graph_importable():
    assert callable(graph.build_graph)
