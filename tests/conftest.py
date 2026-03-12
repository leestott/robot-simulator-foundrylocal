"""pytest configuration – exclude standalone integration scripts."""

collect_ignore = [
    "test_integration.py",
    "test_render_screenshots.py",
    "test_render_app_screenshots.py",
]
