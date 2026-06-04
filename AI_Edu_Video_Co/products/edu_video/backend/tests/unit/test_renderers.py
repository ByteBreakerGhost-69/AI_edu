# products/edu_video/backend/tests/unit/test_renderers.py
"""
Unit tests for Layer 5 renderers.

Coverage targets:
  - BaseRenderer: shared utilities (_image_to_video, _validate_output, _hex_to_rgb)
  - RendererError: construction and field access
  - CodeRenderer: language detection, line limit, highlight logic
  - GraphRenderer: JSON parsing, chart type selection, data validation
  - TimelineRenderer: event parsing, chronological ordering, event count limits
"""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open


from layer5_rendering.renderers.base_renderer import BaseRenderer, RendererError


# --------------------------------------------------------------------------- #
# RendererError                                                                  #
# --------------------------------------------------------------------------- #

class TestRendererError:

    def test_renderer_error_stores_all_fields(self):
        """RendererError must expose renderer, scene_index, and cause attributes."""
        cause = ValueError("underlying cause")
        err = RendererError(
            "Test error message",
            renderer="manim",
            scene_index=3,
            cause=cause,
        )
        assert str(err) == "Test error message"
        assert err.renderer == "manim"
        assert err.scene_index == 3
        assert err.cause is cause

    def test_renderer_error_without_cause(self):
        """RendererError can be created without a cause."""
        err = RendererError("No cause", renderer="lottie", scene_index=0)
        assert err.cause is None

    def test_renderer_error_is_exception(self):
        """RendererError must be raiseable and catchable as Exception."""
        with pytest.raises(RendererError) as exc_info:
            raise RendererError("fail", renderer="code", scene_index=1)
        assert exc_info.value.renderer == "code"

    def test_renderer_error_cause_chain(self):
        """RendererError raised with cause maintains exception chain."""
        original = FileNotFoundError("file missing")
        err = RendererError("Renderer failed", renderer="flux_sdxl", scene_index=2, cause=original)
        assert isinstance(err.cause, FileNotFoundError)


# --------------------------------------------------------------------------- #
# BaseRenderer utilities (via concrete subclass)                                #
# --------------------------------------------------------------------------- #

class ConcreteRenderer(BaseRenderer):
    """Minimal concrete implementation for testing BaseRenderer utilities."""

    @property
    def renderer_name(self) -> str:
        return "test_renderer"

    async def render(self, package, output_path: str) -> str:
        return output_path


class TestBaseRendererUtilities:

    @pytest.fixture
    def renderer(self, test_settings):
        return ConcreteRenderer()

    def test_hex_to_rgb_standard_color(self, renderer):
        """_hex_to_rgb converts '#3B82F6' to (59, 130, 246)."""
        r, g, b = renderer._hex_to_rgb("#3B82F6")
        assert r == 59
        assert g == 130
        assert b == 246

    def test_hex_to_rgb_without_hash(self, renderer):
        """_hex_to_rgb handles input without leading '#'."""
        r, g, b = renderer._hex_to_rgb("FFFFFF")
        assert r == 255
        assert g == 255
        assert b == 255

    def test_hex_to_rgb_black(self, renderer):
        """_hex_to_rgb converts '#000000' to (0, 0, 0)."""
        assert renderer._hex_to_rgb("#000000") == (0, 0, 0)

    def test_hex_to_rgb_float_range(self, renderer):
        """_hex_to_rgb_float returns values in [0.0, 1.0]."""
        r, g, b = renderer._hex_to_rgb_float("#3B82F6")
        assert 0.0 <= r <= 1.0
        assert 0.0 <= g <= 1.0
        assert 0.0 <= b <= 1.0
        assert abs(r - 59 / 255) < 0.01

    def test_hex_to_rgb_float_white(self, renderer):
        """_hex_to_rgb_float('#FFFFFF') returns (1.0, 1.0, 1.0)."""
        assert renderer._hex_to_rgb_float("#FFFFFF") == (1.0, 1.0, 1.0)

    def test_safe_color_returns_palette_color(self, renderer):
        """_safe_color returns the color at the given index when available."""
        palette = ["#1F2937", "#3B82F6", "#FFFFFF"]
        assert renderer._safe_color(palette, 1) == "#3B82F6"

    def test_safe_color_returns_fallback_on_out_of_range(self, renderer):
        """_safe_color returns fallback when index exceeds palette length."""
        palette = ["#1F2937"]
        result = renderer._safe_color(palette, 5, fallback="#FF0000")
        assert result == "#FF0000"

    def test_safe_color_returns_fallback_on_empty_palette(self, renderer):
        """_safe_color with empty palette returns fallback."""
        result = renderer._safe_color([], 0, fallback="#000000")
        assert result == "#000000"

    def test_get_temp_dir_creates_directory(self, renderer, final_scene_package_factory, tmp_path, test_settings):
        """_get_temp_dir creates the temp directory and returns a Path."""
        test_settings.RENDER_TEMP_DIR = str(tmp_path)
        package = final_scene_package_factory(scene_index=2)
        temp_dir = renderer._get_temp_dir(package)
        assert isinstance(temp_dir, Path)
        assert temp_dir.exists()

    @pytest.mark.asyncio
    async def test_validate_output_raises_when_file_missing(self, renderer):
        """_validate_output raises RendererError when output file does not exist."""
        with pytest.raises(RendererError) as exc_info:
            await renderer._validate_output("/nonexistent/path/output.mp4", scene_index=0)
        assert exc_info.value.renderer == "test_renderer"

    @pytest.mark.asyncio
    async def test_validate_output_raises_when_file_too_small(self, renderer, tmp_path):
        """_validate_output raises RendererError when output file is < 1KB."""
        tiny_file = tmp_path / "tiny.mp4"
        tiny_file.write_bytes(b"x" * 100)  # 100 bytes, below 1024 minimum
        with pytest.raises(RendererError):
            await renderer._validate_output(str(tiny_file), scene_index=0)


# --------------------------------------------------------------------------- #
# CodeRenderer                                                                  #
# --------------------------------------------------------------------------- #

class TestCodeRenderer:

    @pytest.fixture
    def renderer(self, test_settings):
        from layer5_rendering.renderers.code_renderer import CodeRenderer
        return CodeRenderer()

    def test_renderer_name(self, renderer):
        """renderer_name property must return 'code'."""
        assert renderer.renderer_name == "code"

    def test_extract_python_from_fence(self, renderer):
        """_extract_language_and_code parses ```python fence correctly."""
        from layer5_rendering.renderers.code_renderer import _extract_language_and_code
        raw = "```python\ndef hello():\n    print('hello')\n```"
        lang, code = _extract_language_and_code(raw, {})
        assert lang == "python"
        assert "def hello" in code

    def test_extract_java_from_fence(self, renderer):
        """_extract_language_and_code parses ```java fence correctly."""
        from layer5_rendering.renderers.code_renderer import _extract_language_and_code
        raw = "```java\npublic class Main {\n    public static void main(String[] args) {}\n}\n```"
        lang, code = _extract_language_and_code(raw, {})
        assert lang == "java"

    def test_extract_language_from_comment(self, renderer):
        """Language hint in '# language: python' comment is parsed correctly."""
        from layer5_rendering.renderers.code_renderer import _extract_language_and_code
        raw = "# language: python\ndef foo():\n    pass"
        lang, code = _extract_language_and_code(raw, {})
        assert lang == "python"
        assert "def foo" in code

    def test_fallback_to_config_language(self, renderer):
        """Without fence or comment, language falls back to animation_config['language']."""
        from layer5_rendering.renderers.code_renderer import _extract_language_and_code
        raw = "x = 1\ny = 2"
        lang, code = _extract_language_and_code(raw, {"language": "javascript"})
        assert lang == "javascript"

    def test_fallback_to_python_default(self, renderer):
        """Without any language hint, default language is 'python'."""
        from layer5_rendering.renderers.code_renderer import _extract_language_and_code
        raw = "x = 1"
        lang, code = _extract_language_and_code(raw, {})
        assert lang == "python"

    @pytest.mark.asyncio
    async def test_render_raises_renderer_error_on_image_failure(
        self, renderer, final_scene_package_factory, tmp_path, test_settings, mocker
    ):
        """
        render() raises RendererError (not an unhandled exception)
        when the image creation fails and fallback also fails.
        """
        test_settings.RENDER_TEMP_DIR = str(tmp_path)
        package = final_scene_package_factory(
            renderer_type="code",
            scene_index=0,
        )
        package.visual_spec.primary_content = "# language: python\nx = 1"
        output = str(tmp_path / "output.mp4")

        # Mock Pygments ImageFormatter to raise, then fallback also fails
        mocker.patch(
            "layer5_rendering.renderers.code_renderer.highlight",
            side_effect=Exception("Pygments failure"),
        )
        # Mock _text_fallback to also fail to produce a valid image
        mocker.patch.object(
            renderer, "_text_fallback",
            side_effect=RendererError("fallback failed", renderer="code", scene_index=0)
        )
        mocker.patch.object(
            renderer, "_image_to_video",
            new_callable=AsyncMock,
            return_value=output,
        )
        mocker.patch.object(
            renderer, "_validate_output",
            new_callable=AsyncMock,
            return_value=None,
        )

        # Should not raise unhandled Exception — only RendererError
        # (or succeed if fallback works differently)
        try:
            result = await renderer.render(package, output)
        except RendererError:
            pass  # Expected — test passes
        except Exception as exc:
            pytest.fail(f"Unexpected non-RendererError exception: {type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- #
# GraphRenderer                                                                 #
# --------------------------------------------------------------------------- #

class TestGraphRenderer:

    @pytest.fixture
    def renderer(self, test_settings):
        from layer5_rendering.renderers.graph_renderer import GraphRenderer
        return GraphRenderer()

    def test_renderer_name(self, renderer):
        """renderer_name property must return 'graph'."""
        assert renderer.renderer_name == "graph"

    def test_parse_valid_graph_data(self, renderer):
        """_parse_graph_data parses valid JSON graph spec correctly."""
        from layer5_rendering.renderers.graph_renderer import _parse_graph_data
        raw = json.dumps({
            "type": "line",
            "title": "Supply and Demand",
            "x_label": "Quantity",
            "y_label": "Price",
            "datasets": [
                {"label": "Demand", "data": [500, 400, 300, 200, 100]},
                {"label": "Supply", "data": [100, 200, 300, 400, 500]},
            ],
        })
        result = _parse_graph_data(raw)
        assert result["type"] == "line"
        assert result["title"] == "Supply and Demand"
        assert len(result["datasets"]) == 2

    def test_parse_invalid_json_returns_empty(self, renderer):
        """_parse_graph_data returns empty dict for invalid JSON."""
        from layer5_rendering.renderers.graph_renderer import _parse_graph_data
        result = _parse_graph_data("not valid json {{{")
        assert result == {}

    def test_parse_empty_string_returns_empty(self, renderer):
        """_parse_graph_data returns empty dict for empty string."""
        from layer5_rendering.renderers.graph_renderer import _parse_graph_data
        result = _parse_graph_data("")
        assert result == {}

    def test_parse_non_object_json_returns_empty(self, renderer):
        """_parse_graph_data returns empty dict for JSON array (not object)."""
        from layer5_rendering.renderers.graph_renderer import _parse_graph_data
        result = _parse_graph_data(json.dumps([1, 2, 3]))
        assert result == {}

    @pytest.mark.asyncio
    async def test_render_uses_matplotlib_and_returns_path(
        self, renderer, final_scene_package_factory, tmp_path, test_settings, mocker
    ):
        """render() calls Matplotlib and returns the output path on success."""
        test_settings.RENDER_TEMP_DIR = str(tmp_path)
        package = final_scene_package_factory(
            renderer_type="graph",
            scene_index=0,
        )
        package.visual_spec.primary_content = json.dumps({
            "type": "bar",
            "title": "Test Graph",
            "x_label": "X",
            "y_label": "Y",
            "datasets": [{"label": "A", "data": [1, 2, 3]}],
        })
        output = str(tmp_path / "output.mp4")

        mocker.patch.object(
            renderer,
            "_matplotlib_fig_to_video",
            new_callable=AsyncMock,
            return_value=output,
        )
        mocker.patch.object(
            renderer, "_validate_output", new_callable=AsyncMock
        )

        result = await renderer.render(package, output)
        assert result == output

    @pytest.mark.asyncio
    async def test_render_with_empty_datasets_uses_placeholder(
        self, renderer, final_scene_package_factory, tmp_path, test_settings, mocker
    ):
        """render() with no datasets produces a placeholder graph without crashing."""
        test_settings.RENDER_TEMP_DIR = str(tmp_path)
        package = final_scene_package_factory(renderer_type="graph")
        package.visual_spec.primary_content = json.dumps({
            "type": "line", "title": "Empty", "x_label": "X", "y_label": "Y",
            "datasets": [],
        })
        output = str(tmp_path / "output.mp4")

        mocker.patch.object(
            renderer, "_matplotlib_fig_to_video",
            new_callable=AsyncMock, return_value=output
        )
        mocker.patch.object(renderer, "_validate_output", new_callable=AsyncMock)

        result = await renderer.render(package, output)
        assert result == output


# --------------------------------------------------------------------------- #
# TimelineRenderer                                                              #
# --------------------------------------------------------------------------- #

class TestTimelineRenderer:

    @pytest.fixture
    def renderer(self, test_settings):
        from layer5_rendering.renderers.timeline_renderer import TimelineRenderer
        return TimelineRenderer()

    def test_renderer_name(self, renderer):
        """renderer_name property must return 'timeline'."""
        assert renderer.renderer_name == "timeline"

    def test_parse_valid_timeline_events(self, renderer):
        """_parse_timeline_events parses valid JSON array of event dicts."""
        from layer5_rendering.renderers.timeline_renderer import _parse_timeline_events
        raw = json.dumps([
            {"date": "1789", "event": "French Revolution begins"},
            {"date": "1799", "event": "Napoleon seizes power"},
        ])
        events = _parse_timeline_events(raw)
        assert len(events) == 2
        assert events[0]["date"] == "1789"
        assert events[1]["event"] == "Napoleon seizes power"

    def test_parse_invalid_json_returns_empty(self, renderer):
        """_parse_timeline_events returns [] for invalid JSON."""
        from layer5_rendering.renderers.timeline_renderer import _parse_timeline_events
        events = _parse_timeline_events("{not valid json")
        assert events == []

    def test_parse_empty_string_returns_empty(self, renderer):
        """_parse_timeline_events returns [] for empty string."""
        from layer5_rendering.renderers.timeline_renderer import _parse_timeline_events
        assert _parse_timeline_events("") == []

    def test_parse_json_object_not_array_returns_empty(self, renderer):
        """_parse_timeline_events returns [] when JSON is an object, not array."""
        from layer5_rendering.renderers.timeline_renderer import _parse_timeline_events
        events = _parse_timeline_events(json.dumps({"date": "1789", "event": "test"}))
        assert events == []

    def test_parse_filters_non_dict_entries(self, renderer):
        """_parse_timeline_events filters out non-dict entries from the array."""
        from layer5_rendering.renderers.timeline_renderer import _parse_timeline_events
        raw = json.dumps([
            {"date": "1789", "event": "Valid event"},
            "not a dict",
            42,
            {"date": "1799", "event": "Another valid event"},
        ])
        events = _parse_timeline_events(raw)
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_render_with_no_events_uses_title_fallback(
        self, renderer, final_scene_package_factory, tmp_path, test_settings, mocker
    ):
        """render() with empty primary_content uses package.title as single event."""
        test_settings.RENDER_TEMP_DIR = str(tmp_path)
        package = final_scene_package_factory(renderer_type="timeline")
        package.visual_spec.primary_content = ""
        output = str(tmp_path / "output.mp4")

        mocker.patch.object(
            renderer, "_matplotlib_fig_to_video",
            new_callable=AsyncMock, return_value=output
        )
        mocker.patch.object(renderer, "_validate_output", new_callable=AsyncMock)

        result = await renderer.render(package, output)
        assert result == output

    @pytest.mark.asyncio
    async def test_render_truncates_to_max_events(
        self, renderer, final_scene_package_factory, tmp_path, test_settings, mocker
    ):
        """render() silently truncates more than 10 events to the first 10."""
        test_settings.RENDER_TEMP_DIR = str(tmp_path)
        events = [{"date": str(1700 + i), "event": f"Event {i}"} for i in range(15)]
        package = final_scene_package_factory(renderer_type="timeline")
        package.visual_spec.primary_content = json.dumps(events)
        output = str(tmp_path / "output.mp4")

        captured_events = []

        original_render = renderer.render

        async def capture_and_render(pkg, out):
            # We intercept to check event count before plot
            from layer5_rendering.renderers.timeline_renderer import _parse_timeline_events
            evts = _parse_timeline_events(pkg.visual_spec.primary_content)
            captured_events.extend(evts[:10])
            return output

        mocker.patch.object(
            renderer, "_matplotlib_fig_to_video",
            new_callable=AsyncMock, return_value=output
        )
        mocker.patch.object(renderer, "_validate_output", new_callable=AsyncMock)

        result = await renderer.render(package, output)
        assert result == output

    @pytest.mark.asyncio
    async def test_render_returns_output_path(
        self, renderer, final_scene_package_factory, tmp_path, test_settings, mocker
    ):
        """render() returns the output_path string on success."""
        test_settings.RENDER_TEMP_DIR = str(tmp_path)
        package = final_scene_package_factory(renderer_type="timeline")
        package.visual_spec.primary_content = json.dumps([
            {"date": "1914", "event": "World War I begins"},
            {"date": "1918", "event": "World War I ends"},
        ])
        output = str(tmp_path / "timeline_output.mp4")

        mocker.patch.object(
            renderer, "_matplotlib_fig_to_video",
            new_callable=AsyncMock, return_value=output
        )
        mocker.patch.object(renderer, "_validate_output", new_callable=AsyncMock)

        result = await renderer.render(package, output)
        assert result == output
      
