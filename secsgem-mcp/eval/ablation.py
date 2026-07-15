"""
- (KG only) vs (KG + MCP 툴) 조건 비교
- 핵심 주장은 WM-811K 기반 시나리오에서도 성립함을 별도 확인
"""
def run_ablation(scenarios):
    return {
        # '클래스→최빈 원인' 고정 응답은 cause_discrimination(metrics.py)이 산출
        "kg_only":    evaluate(scenarios, tools_enabled=False),  # 문헌 KG만
        "kg_plus_mcp":evaluate(scenarios, tools_enabled=True),   # KG + MCP
    }
    
    
# 실행 스크립트
# python -m eval.ablation --scenarios simulator/scenarios --out eval/results.json