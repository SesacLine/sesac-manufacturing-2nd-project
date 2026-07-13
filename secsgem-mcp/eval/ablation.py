"""
- (KG only) vs (KG + MCP 툴) 조건 비교
- 핵심 주장은 WM-811K 기반 시나리오에서도 성립함을 별도 확인
"""
def run_ablation(scenarios):
    return {
        "kg_only":    evaluate(scenarios, tools_enabled=False),  # 문헌 KG만
        "kg_plus_mcp":evaluate(scenarios, tools_enabled=True),   # KG + MCP
        # WM-811K만으로도 성립 확인 (GAN 생성분 영향 배제, §10-3)
        "kg_plus_mcp_wm811k_only":
            evaluate([s for s in scenarios if s.source == "wm811k"], tools_enabled=True),
    }