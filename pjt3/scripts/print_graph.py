"""LangGraph 구조를 Mermaid 로 출력한다 (4.2 '그래프 구조 출력'): python -m scripts.print_graph"""
from agent.graph import GRAPH

print(GRAPH.get_graph().draw_mermaid())