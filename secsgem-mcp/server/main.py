from fastmcp import FastMCP
from server.tools import (
    wafer, lot, commonality, normal_ratio, telemetry,
    alarm, maintenance, change_point, timeline)

mcp = FastMCP("secsgem-mcp")
for mod in (wafer, lot, commonality, normal_ratio, telemetry,
            alarm, maintenance, change_point, timeline):
    mod.register(mcp)

if __name__ == "__main__":
    mcp.run()   # stdio; LangGraph/(OPTION)Claude 클라이언트에서 연결