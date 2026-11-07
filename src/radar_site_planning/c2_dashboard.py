"""Interactive Folium & Plotly C2 Visualizations for 11+ Radar Networks (GH-12)."""

from __future__ import annotations

from pathlib import Path

import folium
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .multi_radar_suite import MobilityType, RadarPlatform
from .terrain_manager import CoordinateTransformer


def generate_folium_c2_map(
    radars: list[RadarPlatform] | dict[str, RadarPlatform],
    coverage_results: dict[str, np.ndarray],
    output_html_path: str | Path,
    utm_epsg: int = 32647,
    target_rcs_m2: float = 1.0,
) -> Path:
    """Generates a multi-layer interactive Folium C2 web map rendering all Fixed and Mobile
    radar sites, Field-of-Regard rings, and composite k-coverage contours.
    """
    out = Path(output_html_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    radar_list = list(radars.values()) if isinstance(radars, dict) else list(radars)
    transformer = CoordinateTransformer(utm_epsg=utm_epsg)

    wgs_coords: list[tuple[float, float]] = []
    for r in radar_list:
        if CoordinateTransformer.is_metric_utm(r.lat, r.lon):
            lon_w, lat_w = transformer.utm_to_wgs84(r.lon, r.lat)
            wgs_coords.append((float(lat_w), float(lon_w)))
        else:
            wgs_coords.append((float(r.lat), float(r.lon)))

    center_lat = float(np.mean([c[0] for c in wgs_coords])) if wgs_coords else 13.75
    center_lon = float(np.mean([c[1] for c in wgs_coords])) if wgs_coords else 100.5

    m = folium.Map(location=[center_lat, center_lon], zoom_start=7, tiles="OpenStreetMap")

    fixed_group = folium.FeatureGroup(name="Fixed Strategic Radars", show=True)
    mobile_group = folium.FeatureGroup(name="Mobile Tactical / cUAS Radars", show=True)
    range_group = folium.FeatureGroup(name="Effective Coverage Rings", show=True)

    for r, (lat_w, lon_w) in zip(radar_list, wgs_coords, strict=False):
        r_eff_m = r.calculate_free_space_rmax(target_rcs_m2)
        is_fixed = r.mobility == MobilityType.FIXED
        color = "#00e5ff" if is_fixed else "#ffab00"

        popup_html = (
            f"<b>{r.site_id}: {r.name}</b><br>"
            f"Brand/Model: {r.brand} {r.model}<br>"
            f"Category: {r.radar_category}<br>"
            f"Mobility: {r.mobility.value} | Tech: {r.tech.value}<br>"
            f"Power: {r.peak_power_kw} kW | Freq: {r.frequency_ghz} GHz<br>"
            f"Effective R_max: {r_eff_m / 1000.0:.1f} km "
            f"(Inst: {r.instrumented_max_range_km} km)<br>"
            f"Tilt (Mech/Elec): {r.mechanical_tilt_deg}° / {r.electronic_tilt_deg}°"
        )

        marker = folium.CircleMarker(
            location=[lat_w, lon_w],
            radius=8 if is_fixed else 6,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.9,
            popup=folium.Popup(popup_html, max_width=320),
            tooltip=f"{r.site_id} ({r.brand} {r.model})",
        )
        if is_fixed:
            marker.add_to(fixed_group)
        else:
            marker.add_to(mobile_group)

        folium.Circle(
            location=[lat_w, lon_w],
            radius=float(r_eff_m),
            color=color,
            weight=1.5,
            fill=True,
            fill_opacity=0.08,
            tooltip=f"{r.site_id} Effective Range ({r_eff_m / 1000.0:.1f} km)",
        ).add_to(range_group)

    fixed_group.add_to(m)
    mobile_group.add_to(m)
    range_group.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)

    m.save(str(out))
    return out


def generate_plotly_c2_dashboard(
    radars: list[RadarPlatform] | dict[str, RadarPlatform],
    coverage_results: dict[str, np.ndarray],
    output_html_path: str | Path | None = None,
    target_rcs_m2: float = 1.0,
) -> go.Figure:
    """Builds a 4-panel interactive Plotly C2 dashboard displaying:
    1. Multi-Station Redundancy (k-Coverage) + Radar Site Overlay
    2. Cumulative Network Detection Probability (P_{d,net})
    3. Maximum Received SNR (dB) Heatmap
    4. Fleet Effective Range vs. Instrumented Limit Comparison
    """
    radar_list = list(radars.values()) if isinstance(radars, dict) else list(radars)
    x_coords = coverage_results["x_coords"]
    y_coords = coverage_results["y_coords"]
    overlap = coverage_results["overlap_count"]
    joint_pd = coverage_results["joint_pd"]
    max_snr = coverage_results["max_snr_db"]

    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "Multi-Station Overlap (k-Coverage)",
            "Joint Network Detection Probability (P_d,net)",
            "Strongest Received Signal-to-Noise Ratio (dB)",
            "Fleet Range Comparison: Effective vs. Instrumented (km)",
        ),
        horizontal_spacing=0.1,
        vertical_spacing=0.14,
    )

    # Panel 1: k-Coverage Heatmap + Radar Sites
    fig.add_trace(
        go.Heatmap(
            x=x_coords,
            y=y_coords,
            z=overlap,
            colorscale="Viridis",
            colorbar={"title": "k", "x": 0.45, "len": 0.42, "y": 0.8},
            name="k-Coverage",
        ),
        row=1,
        col=1,
    )

    if radar_list:
        fig.add_trace(
            go.Scatter(
                x=[r.lon for r in radar_list],
                y=[r.lat for r in radar_list],
                mode="markers+text",
                text=[r.site_id for r in radar_list],
                textposition="top center",
                marker={
                    "size": 10,
                    "color": [
                        "#00e5ff" if r.mobility == MobilityType.FIXED else "#ffab00"
                        for r in radar_list
                    ],
                    "line": {"width": 1, "color": "black"},
                },
                name="Radar Sites",
            ),
            row=1,
            col=1,
        )

    # Panel 2: Joint Pd Heatmap
    fig.add_trace(
        go.Heatmap(
            x=x_coords,
            y=y_coords,
            z=joint_pd,
            zmin=0.0,
            zmax=1.0,
            colorscale="Plasma",
            colorbar={"title": "P_d,net", "x": 1.0, "len": 0.42, "y": 0.8},
            name="Joint Pd",
        ),
        row=1,
        col=2,
    )

    # Panel 3: Max SNR (dB) Heatmap
    fig.add_trace(
        go.Heatmap(
            x=x_coords,
            y=y_coords,
            z=max_snr,
            colorscale="Turbo",
            colorbar={"title": "SNR (dB)", "x": 0.45, "len": 0.42, "y": 0.2},
            name="Max SNR (dB)",
        ),
        row=2,
        col=1,
    )

    # Panel 4: Fleet Range Bar Chart
    site_ids = [r.site_id for r in radar_list]
    eff_ranges = [round(r.calculate_free_space_rmax(target_rcs_m2) / 1000.0, 2) for r in radar_list]
    inst_ranges = [r.instrumented_max_range_km for r in radar_list]

    fig.add_trace(
        go.Bar(name="Effective R_max (km)", x=site_ids, y=eff_ranges, marker_color="#00e5ff"),
        row=2,
        col=2,
    )
    fig.add_trace(
        go.Bar(name="Instrumented Limit (km)", x=site_ids, y=inst_ranges, marker_color="#ff6d00"),
        row=2,
        col=2,
    )

    fig.update_layout(
        title_text="Integrated Multi-Radar Network Planning & RF Coverage C2 Dashboard",
        template="plotly_dark",
        height=900,
        width=1400,
        barmode="group",
        showlegend=True,
    )

    if output_html_path is not None:
        out = Path(output_html_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(str(out), include_plotlyjs="cdn")

    return fig
