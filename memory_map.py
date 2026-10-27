# -*- coding: utf-8 -*-
"""Generate an interactive memory graph from tag_index.json.

Usage:
    pip install -r requirements-viz.txt
    python memory_map.py --out memory_map.html
"""

import argparse
import json
from pathlib import Path

import config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="memory_map.html")
    args = parser.parse_args()

    try:
        import networkx as nx
        from pyecharts import options as opts
        from pyecharts.charts import Graph
    except ImportError:
        print("Install visualization extras first: pip install -r requirements-viz.txt")
        return 1

    index_path = config.BOT_HOME / "tag_index.json"
    if not index_path.exists():
        print("No tag_index.json yet. Send a few messages first:", index_path)
        return 1

    tags = json.loads(index_path.read_text(encoding="utf-8")).get("tags") or {}
    graph = nx.Graph()
    for tag, files in tags.items():
        graph.add_node(tag, kind="tag")
        for rel in files:
            graph.add_node(rel, kind="file")
            graph.add_edge(tag, rel)
    if not graph.nodes:
        print("Index is empty.")
        return 1

    pos = nx.spring_layout(graph, seed=42, k=0.8)
    nodes, links = [], []
    for name, data in graph.nodes(data=True):
        kind = data.get("kind", "file")
        x, y = pos[name]
        nodes.append(opts.GraphNode(
            name=Path(name).name if kind == "file" else name,
            x=float(x), y=float(y),
            symbol_size=28 if kind == "tag" else 14,
            value=kind,
        ))
    for a, b in graph.edges():
        links.append(opts.GraphLink(
            source=Path(a).name if graph.nodes[a].get("kind") == "file" else a,
            target=Path(b).name if graph.nodes[b].get("kind") == "file" else b,
        ))

    chart = (
        Graph(init_opts=opts.InitOpts(width="100%", height="760px", bg_color="#0b1020"))
        .add("", nodes, links, repulsion=500, edge_length=80, is_roam=True,
             label_opts=opts.LabelOpts(is_show=True, color="#dbeafe", font_size=11),
             linestyle_opts=opts.LineStyleOpts(width=1, opacity=0.35, color="#64748b"))
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="Physical memory map",
                subtitle="Built from tag_index.json — no fake graph, no cloud",
                pos_left="center", title_textstyle_opts=opts.TextStyleOpts(color="#e2e8f0"),
                subtitle_textstyle_opts=opts.TextStyleOpts(color="#94a3b8")),
            legend_opts=opts.LegendOpts(is_show=False),
            tooltip_opts=opts.TooltipOpts(trigger="item"),
        )
    )
    chart.render(args.out)
    print("Wrote", args.out, "— nodes:", len(nodes), "edges:", len(links))
    print("This map reads tag_index.json directly. If a demo does not, it is a skin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
