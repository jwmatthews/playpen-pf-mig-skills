#!/usr/bin/env python3
"""
Compare baseline and post-migration screenshots using pixel-level analysis.

Produces a structured JSON report of differences, eliminating the need for
the agent to load images multiple times or write ad-hoc PIL scripts.

The agent receives a text report and only needs to act on real differences.

Usage:
  python3 compare_screenshots.py <baseline_dir> <compare_dir> [--threshold 0.5] [--channel-tolerance 15]

Output: JSON to stdout with per-image comparison results.
"""

import sys
import json
import argparse
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow is required. Install with: pip install Pillow", file=sys.stderr)
    sys.exit(1)


def compare_images(baseline_path, compare_path, threshold_pct=0.5, channel_tolerance=15):
    """Compare two images pixel by pixel.

    Returns a dict with comparison results:
    - identical: True if images are pixel-identical
    - anti_aliasing_only: True if differences are below noise threshold
    - diff_percentage: percentage of pixels that differ
    - max_channel_diff: maximum per-channel difference found
    - size_match: whether dimensions match
    - regions: list of bounding boxes where differences concentrate
    """
    try:
        img1 = Image.open(baseline_path).convert('RGB')
        img2 = Image.open(compare_path).convert('RGB')
    except Exception as e:
        return {'error': str(e)}

    result = {
        'baseline_size': list(img1.size),
        'compare_size': list(img2.size),
        'size_match': img1.size == img2.size,
    }

    if not result['size_match']:
        result['identical'] = False
        result['anti_aliasing_only'] = False
        result['diff_percentage'] = 100.0
        result['max_channel_diff'] = 255
        result['summary'] = f"Size mismatch: baseline {img1.size} vs post-migration {img2.size}"
        return result

    w, h = img1.size
    total_pixels = w * h
    pixels1 = img1.load()
    pixels2 = img2.load()

    diff_count = 0
    max_channel_diff = 0
    # Track difference regions using a grid
    grid_size = 50  # divide image into 50x50 cells
    grid_w = max(1, w // grid_size)
    grid_h = max(1, h // grid_size)
    grid = [[0] * grid_w for _ in range(grid_h)]

    for y in range(h):
        for x in range(w):
            r1, g1, b1 = pixels1[x, y]
            r2, g2, b2 = pixels2[x, y]
            dr = abs(r1 - r2)
            dg = abs(g1 - g2)
            db = abs(b1 - b2)
            max_d = max(dr, dg, db)
            if max_d > 0:
                diff_count += 1
                max_channel_diff = max(max_channel_diff, max_d)
                gx = min(x // grid_size, grid_w - 1)
                gy = min(y // grid_size, grid_h - 1)
                grid[gy][gx] += 1

    diff_pct = (diff_count / total_pixels) * 100 if total_pixels > 0 else 0

    result['identical'] = diff_count == 0
    result['diff_percentage'] = round(diff_pct, 3)
    result['max_channel_diff'] = max_channel_diff
    result['diff_pixels'] = diff_count
    result['total_pixels'] = total_pixels

    # Classify as anti-aliasing noise
    result['anti_aliasing_only'] = (
        diff_pct < threshold_pct and max_channel_diff <= channel_tolerance
    )

    # Find regions with highest concentration of differences
    if diff_count > 0 and not result['anti_aliasing_only']:
        regions = []
        for gy in range(grid_h):
            for gx in range(grid_w):
                cell_pixels = grid_size * grid_size
                cell_diff_pct = (grid[gy][gx] / cell_pixels) * 100 if cell_pixels > 0 else 0
                if cell_diff_pct > 1.0:  # More than 1% of cell pixels differ
                    regions.append({
                        'x': gx * grid_size,
                        'y': gy * grid_size,
                        'width': grid_size,
                        'height': grid_size,
                        'diff_pixels': grid[gy][gx],
                        'diff_pct': round(cell_diff_pct, 1),
                        'location': describe_location(gx, gy, grid_w, grid_h),
                    })
        # Sort by diff count descending, limit to top 10
        regions.sort(key=lambda r: r['diff_pixels'], reverse=True)
        result['diff_regions'] = regions[:10]

    if result['identical']:
        result['summary'] = "Identical"
    elif result['anti_aliasing_only']:
        result['summary'] = f"Anti-aliasing noise only ({diff_pct:.2f}% pixels, max {max_channel_diff} channel diff)"
    else:
        result['summary'] = f"{diff_pct:.2f}% pixels differ (max channel diff: {max_channel_diff})"

    return result


def describe_location(gx, gy, grid_w, grid_h):
    """Describe a grid cell location in human terms."""
    # Vertical position
    if gy < grid_h * 0.2:
        v = "top"
    elif gy > grid_h * 0.8:
        v = "bottom"
    else:
        v = "middle"

    # Horizontal position
    if gx < grid_w * 0.2:
        h = "left"
    elif gx > grid_w * 0.8:
        h = "right"
    else:
        h = "center"

    return f"{v}-{h}"


def main():
    parser = argparse.ArgumentParser(description="Compare baseline and post-migration screenshots")
    parser.add_argument('baseline_dir', help='Directory containing baseline screenshots')
    parser.add_argument('compare_dir', help='Directory containing post-migration screenshots')
    parser.add_argument('--threshold', type=float, default=0.5,
                        help='Diff percentage threshold for anti-aliasing filter (default: 0.5)')
    parser.add_argument('--channel-tolerance', type=int, default=15,
                        help='Max per-channel difference for anti-aliasing filter (default: 15)')

    args = parser.parse_args()

    baseline_dir = Path(args.baseline_dir)
    compare_dir = Path(args.compare_dir)

    if not baseline_dir.is_dir():
        print(f"Error: Baseline directory not found: {baseline_dir}", file=sys.stderr)
        sys.exit(1)
    if not compare_dir.is_dir():
        print(f"Error: Compare directory not found: {compare_dir}", file=sys.stderr)
        sys.exit(1)

    baseline_files = {f.name for f in baseline_dir.glob('*.png')}
    compare_files = {f.name for f in compare_dir.glob('*.png')}

    all_names = sorted(baseline_files | compare_files)

    results = {
        'baseline_dir': str(baseline_dir),
        'compare_dir': str(compare_dir),
        'comparisons': [],
        'summary': {
            'identical': 0,
            'anti_aliasing_only': 0,
            'different': 0,
            'missing_baseline': 0,
            'missing_post_migration': 0,
        }
    }

    for name in all_names:
        entry = {'name': name}

        if name not in baseline_files:
            entry['status'] = 'missing_baseline'
            entry['summary'] = 'Missing from baseline directory'
            results['summary']['missing_baseline'] += 1
        elif name not in compare_files:
            entry['status'] = 'missing_post_migration'
            entry['summary'] = 'Missing from post-migration directory'
            results['summary']['missing_post_migration'] += 1
        else:
            comparison = compare_images(
                baseline_dir / name,
                compare_dir / name,
                args.threshold,
                args.channel_tolerance,
            )
            entry.update(comparison)

            if comparison.get('identical'):
                entry['status'] = 'identical'
                results['summary']['identical'] += 1
            elif comparison.get('anti_aliasing_only'):
                entry['status'] = 'anti_aliasing_only'
                results['summary']['anti_aliasing_only'] += 1
            else:
                entry['status'] = 'different'
                results['summary']['different'] += 1

        results['comparisons'].append(entry)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
