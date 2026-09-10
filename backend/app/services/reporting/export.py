"""The structured data export the BRD asks for alongside the PDF.

Pure, like the renderer: a context dictionary in, a JSON-serialisable
dictionary out.
"""

from __future__ import annotations

from typing import Any

def structured_export(ctx: dict[str, Any]) -> dict[str, Any]:
    """The exportable structured data the BRD asks for alongside the PDF."""
    locale = ctx["locale"]
    axes = ctx["axes"]
    return {
        "organisation": {
            "id": ctx["org"].id if ctx["org"] else None,
            "name_ar": ctx["org"].name_ar if ctx["org"] else None,
            "name_en": ctx["org"].name_en if ctx["org"] else None,
        },
        "assessment": {
            "id": ctx["assessment"].id,
            "name": ctx["assessment"].name,
            "layer": ctx["assessment"].layer,
            "status": ctx["assessment"].status,
            "submitted_at": ctx["assessment"].submitted_at.isoformat()
            if ctx["assessment"].submitted_at
            else None,
        },
        "framework_version": {
            "id": ctx["version"].id if ctx["version"] else None,
            "version": ctx["version"].version if ctx["version"] else None,
            "scoring_config": ctx["version"].scoring_config if ctx["version"] else {},
        },
        "scoring": ctx["result"],
        "axis_names": {
            axis_id: {"ar": axis.name_ar, "en": axis.name_en} for axis_id, axis in axes.items()
        },
        "initiatives": [
            {
                "title_ar": i.title_ar,
                "title_en": i.title_en,
                "axis_id": i.axis_id,
                "priority": i.priority,
                "horizon": i.horizon_code,
                "linked_gap": i.linked_gap,
                "source": i.source,
            }
            for i in ctx["initiatives"]
        ],
        "generated_at": ctx["generated_at"].isoformat(),
        "locale": locale,
    }
