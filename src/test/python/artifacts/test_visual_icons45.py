from __future__ import annotations

import hashlib
import json
import re
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from xml.etree import ElementTree

import pytest

from orchestwin.artifacts import visual_icons
from orchestwin.artifacts.generated_mockups import (
    SVG_ATTRIBUTES,
    MarkupElement,
    parse_markup,
    serialize_markup,
)
from orchestwin.artifacts.visual_icons import (
    DEFAULT_PICTURE_TONE,
    FALLBACK_ICON,
    FALLBACK_PICTURE,
    ICON_ATTRIBUTES,
    ICON_DIRECTORY,
    ICON_ELEMENTS,
    ICON_LICENCE,
    ICON_NAME,
    ICON_PACKAGE,
    ICON_VIEWBOX,
    MANIFEST_FILE,
    MANIFEST_HASH,
    MAX_ICON_NAME_LENGTH,
    PICTURE_ASPECT,
    PICTURE_COLOURS,
    PICTURE_TONES,
    PICTURE_VIEWBOX,
    icon_body,
    icon_names,
    is_bundled_icon,
    mockup_resources,
    picture_body,
)

from .test_generated_mockup_support import TOKEN_NAMES

ICON_COUNT = 237
LICENCE_FILE = "lucide-LICENSE.txt"
SEARCH = '<path d="m21 21-4.34-4.34"></path><circle cx="11" cy="11" r="8"></circle>'
FAKE_ICONS = {
    "circle": '  <circle cx="12" cy="12" r="10" />\n',
    "image": (
        '  <rect width="18" height="18" x="3" y="3" rx="2" ry="2" />\n'
        '  <circle cx="9" cy="9" r="2" />\n'
        '  <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />\n'
    ),
    "tag": (
        '  <path d="M2 4v7l9 9 7-7-9-9z" />\n'
        '  <circle cx="7.5" cy="7.5" r=".5" fill="currentColor" />\n'
    ),
}


def clear_icons() -> None:
    visual_icons._manifest.cache_clear()
    visual_icons.icon_names.cache_clear()
    visual_icons.icon_body.cache_clear()


@pytest.fixture
def fresh():
    clear_icons()
    yield
    clear_icons()


def lucide(name: str, children: str) -> bytes:
    return (
        "<!-- @license lucide-static v1.54.0 - ISC -->\n"
        "<svg\n"
        f'  class="lucide lucide-{name}"\n'
        '  xmlns="http://www.w3.org/2000/svg"\n'
        '  width="24"\n'
        '  height="24"\n'
        '  viewBox="0 0 24 24"\n'
        '  fill="none"\n'
        '  stroke="currentColor"\n'
        '  stroke-width="2"\n'
        '  stroke-linecap="round"\n'
        '  stroke-linejoin="round"\n'
        ">\n"
        f"{children}"
        "</svg>\n"
    ).encode()


def manifest_bytes(icons: dict[str, bytes], *, licence: str = ICON_LICENCE) -> bytes:
    entries = {
        f"{name}.svg": hashlib.sha256(content).hexdigest()
        for name, content in sorted(icons.items())
    }
    manifest = {"files": entries, "licence": licence, "source": "lucide-static 1.54.0"}
    return json.dumps(manifest, indent=2).encode("utf-8")


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fresh):
    folder = tmp_path / ICON_DIRECTORY
    folder.mkdir()
    monkeypatch.setattr(visual_icons, "files", lambda package: tmp_path)

    def install(icons: dict[str, bytes] | None = None, manifest: bytes | None = None) -> Path:
        chosen = icons or {name: lucide(name, body) for name, body in FAKE_ICONS.items()}
        for name, content in chosen.items():
            (folder / f"{name}.svg").write_bytes(content)
        data = manifest_bytes(chosen) if manifest is None else manifest
        (folder / MANIFEST_FILE).write_bytes(data)
        monkeypatch.setattr(visual_icons, "MANIFEST_HASH", hashlib.sha256(data).hexdigest())
        return folder

    return install


def test_the_constants_are_those_of_the_contract() -> None:
    assert (ICON_PACKAGE, ICON_DIRECTORY, ICON_LICENCE) == ("orchestwin.artifacts", "icons", "ISC")
    assert MANIFEST_FILE == "MANIFEST.json"
    assert re.fullmatch(r"[0-9a-f]{64}", MANIFEST_HASH)
    assert ICON_NAME.pattern == r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
    assert (MAX_ICON_NAME_LENGTH, FALLBACK_ICON, FALLBACK_PICTURE) == (48, "circle", "image")
    assert ICON_VIEWBOX == "0 0 24 24"
    assert ICON_ATTRIBUTES == (
        ("viewbox", "0 0 24 24"),
        ("fill", "none"),
        ("stroke", "currentColor"),
        ("stroke-width", "2"),
        ("stroke-linecap", "round"),
        ("stroke-linejoin", "round"),
    )
    assert {"path", "circle", "rect", "line", "polyline", "polygon", "ellipse"} == ICON_ELEMENTS
    assert (PICTURE_VIEWBOX, PICTURE_ASPECT) == ("0 0 400 300", "xMidYMid slice")
    assert PICTURE_TONES == ("primary", "accent", "neutral", "success", "danger")
    assert DEFAULT_PICTURE_TONE == "primary"
    assert tuple(PICTURE_COLOURS) == PICTURE_TONES
    assert dict(PICTURE_COLOURS) == {
        "primary": "primary",
        "accent": "accent",
        "neutral": "text-muted",
        "success": "success",
        "danger": "danger",
    }
    assert isinstance(PICTURE_COLOURS, MappingProxyType)


def test_the_manifest_of_the_disk_has_its_recorded_hash_and_names_every_icon_file() -> None:
    directory = files(ICON_PACKAGE) / ICON_DIRECTORY
    content = (directory / MANIFEST_FILE).read_bytes()
    manifest = json.loads(content.decode("utf-8"))

    assert (
        Path(str(directory)).resolve() == (Path(visual_icons.__file__).parent / "icons").resolve()
    )
    assert hashlib.sha256(content).hexdigest() == MANIFEST_HASH
    assert set(manifest) == {"files", "licence", "source"}
    assert (manifest["licence"], manifest["source"]) == ("ISC", "lucide-static 1.54.0")
    assert len(manifest["files"]) == ICON_COUNT
    assert {item.name for item in directory.iterdir()} == set(manifest["files"]) | {
        MANIFEST_FILE,
        LICENCE_FILE,
    }
    assert (directory / LICENCE_FILE).read_text(encoding="utf-8").startswith("ISC License")
    for file_name, digest in manifest["files"].items():
        assert hashlib.sha256((directory / file_name).read_bytes()).hexdigest() == digest


def test_the_names_are_the_sorted_names_of_the_manifest_read_once(fresh) -> None:
    names = icon_names()

    assert names == tuple(sorted(set(names)))
    assert len(names) == ICON_COUNT
    assert all(ICON_NAME.fullmatch(name) and len(name) <= MAX_ICON_NAME_LENGTH for name in names)
    assert {FALLBACK_ICON, FALLBACK_PICTURE, "search", "package", "x"} <= set(names)
    assert icon_names() is names
    assert is_bundled_icon("search") and icon_body("search")
    assert visual_icons._manifest.cache_info().misses == 1


def test_every_icon_of_the_disk_is_a_plain_line_drawing_named_like_its_file() -> None:
    directory = files(ICON_PACKAGE) / ICON_DIRECTORY
    for name in icon_names():
        root = ElementTree.fromstring((directory / f"{name}.svg").read_bytes())
        body = icon_body(name)
        nodes = parse_markup(f"<svg>{body}</svg>", screen_code="SCR-001", screen_codes=())
        shapes = nodes[0].children

        assert f"lucide-{name}" in root.get("class", "").split(), name
        assert serialize_markup(nodes) == f"<svg>{body}</svg>", name
        assert len(shapes) == len(root) > 0, name
        assert all(isinstance(shape, MarkupElement) for shape in shapes), name
        assert {shape.name for shape in shapes} <= ICON_ELEMENTS, name
        for shape in shapes:
            assert not shape.children, name
            assert {key for key, _value in shape.attributes} <= SVG_ATTRIBUTES, name
        assert len(body.encode("utf-8")) < 1000, name


def test_a_known_icon_is_written_in_the_form_of_the_repository() -> None:
    assert icon_body("search") == SEARCH
    assert icon_body("alert-circle") == (
        '<circle cx="12" cy="12" r="10"></circle>'
        '<line x1="12" x2="12" y1="8" y2="12"></line>'
        '<line x1="12" x2="12.01" y1="16" y2="16"></line>'
    )
    assert '<circle cx="7.5" cy="7.5" fill="currentColor" r=".5"></circle>' in icon_body("tag")


def test_every_icon_file_is_read_once(fresh) -> None:
    icon_body("search")
    icon_body("search")
    picture_body("search", "primary", 1)

    info = visual_icons.icon_body.cache_info()
    assert (info.misses, info.hits) == (1, 2)


@pytest.mark.parametrize(
    "name",
    [
        "magnifying-glass",
        "Search",
        "search ",
        "",
        "search.svg",
        "../search",
        "a" * 49,
        "MANIFEST",
        "lucide-LICENSE",
        None,
        3,
    ],
)
def test_an_unknown_icon_raises_a_key_error(name: object) -> None:
    assert not is_bundled_icon(name)
    with pytest.raises(KeyError):
        icon_body(name)


def test_a_manifest_that_does_not_match_its_recorded_hash_is_refused(fresh, monkeypatch) -> None:
    monkeypatch.setattr(visual_icons, "MANIFEST_HASH", "0" * 64)

    with pytest.raises(RuntimeError, match="manifest does not match"):
        icon_names()
    with pytest.raises(RuntimeError, match="manifest does not match"):
        icon_body("search")
    with pytest.raises(RuntimeError, match="manifest does not match"):
        mockup_resources()


def test_the_icons_are_read_from_the_directory_of_the_package(bundle) -> None:
    bundle()

    assert icon_names() == ("circle", "image", "tag")
    assert icon_body("circle") == '<circle cx="12" cy="12" r="10"></circle>'
    assert icon_body("tag") == (
        '<path d="M2 4v7l9 9 7-7-9-9z"></path>'
        '<circle cx="7.5" cy="7.5" fill="currentColor" r=".5"></circle>'
    )
    assert mockup_resources()["icons"] == ["circle", "image", "tag"]
    with pytest.raises(KeyError):
        icon_body("search")


def test_an_icon_file_that_does_not_match_the_manifest_or_is_missing_is_refused(bundle) -> None:
    folder = bundle()
    (folder / "tag.svg").write_bytes(lucide("tag", '  <path d="M2 4v8" />\n'))
    (folder / "image.svg").unlink()

    with pytest.raises(RuntimeError, match="tag does not match its recorded hash"):
        icon_body("tag")
    with pytest.raises(RuntimeError, match="image is missing"):
        icon_body("image")
    assert icon_body("circle")


@pytest.mark.parametrize(
    "children",
    [
        '  <text x="1" y="1">x</text>\n',
        "  <script>alert(1)</script>\n",
        '  <use href="#x" />\n',
        '  <g><path d="M0 0" /></g>\n',
        '  <image href="x.png" width="1" height="1" />\n',
        '  <path d="M0 0" onclick="alert(1)" />\n',
        '  <path d="M0 0" style="fill:red" />\n',
        '  <path d="M0 0" class="x" />\n',
        '  <path xmlns:l="http://www.w3.org/1999/xlink" d="M0 0" l:href="#x" />\n',
        '  <path d="M0 0" fill="url(#x)" />\n',
        '  <path d="M0 0" stroke="red" />\n',
        '  <path d="javascript:alert(1)" />\n',
        '  <path d="M0 0">x</path>\n',
        '  <path d="M0 0"><title>x</title></path>\n',
        '  text <path d="M0 0" />\n',
        '  <path d="M0 0" /> tail\n',
    ],
)
def test_an_icon_with_an_element_or_attribute_outside_the_lists_is_refused(
    bundle, children: str
) -> None:
    bundle({"circle": lucide("circle", children)})

    with pytest.raises(RuntimeError, match="circle is not a plain line drawing"):
        icon_body("circle")


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b'viewBox="0 0 24 24"', b'viewBox="0 0 16 16"'),
        (b'fill="none"', b'fill="currentColor"'),
        (b'stroke-width="2"', b'stroke-width="1.5"'),
        (b'stroke-linecap="round"', b'stroke-linecap="square"'),
        (b"http://www.w3.org/2000/svg", b"http://www.w3.org/1999/xhtml"),
        (b"</svg>", b"</svg"),
        (b'  stroke="currentColor"\n', b""),
    ],
)
def test_an_icon_whose_frame_differs_from_the_composed_frame_is_refused(
    bundle, old: bytes, new: bytes
) -> None:
    content = lucide("circle", FAKE_ICONS["circle"])
    assert old in content
    bundle({"circle": content.replace(old, new)})

    with pytest.raises(RuntimeError, match="circle is not a plain line drawing"):
        icon_body("circle")


def test_without_a_manifest_the_icons_are_not_bundled(fresh, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(visual_icons, "files", lambda package: tmp_path)

    with pytest.raises(RuntimeError, match="the icons are not bundled"):
        icon_names()
    with pytest.raises(RuntimeError, match="the icons are not bundled"):
        is_bundled_icon("circle")


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        (b"not json", "cannot be read"),
        (b"\xff\xfe", "cannot be read"),
        (b"[]", "cannot be read"),
        (b'{"files": {}, "licence": "ISC"}', "cannot be read"),
        (b'{"files": [], "licence": "ISC"}', "cannot be read"),
        (b'{"files": {"circle.svg": "' + b"0" * 64 + b'"}, "licence": "MIT"}', "cannot be read"),
        (b'{"files": {"Circle.svg": "' + b"0" * 64 + b'"}, "licence": "ISC"}', "not an icon"),
        (b'{"files": {"circle.png": "' + b"0" * 64 + b'"}, "licence": "ISC"}', "not an icon"),
        (b'{"files": {"circle.svg": "XYZ"}, "licence": "ISC"}', "not an icon"),
        (b'{"files": {"circle.svg": 7}, "licence": "ISC"}', "not an icon"),
    ],
)
def test_a_manifest_in_another_form_is_refused(bundle, manifest: bytes, message: str) -> None:
    bundle(manifest=manifest)

    with pytest.raises(RuntimeError, match=message):
        icon_names()


def test_a_picture_is_a_flat_tint_with_the_icon_in_the_middle() -> None:
    expected = (
        '<rect width="400" height="300" '
        'style="fill:color-mix(in srgb, var(--vl-color-accent) 14%, var(--vl-color-surface))">'
        "</rect>"
        '<g transform="translate(128 78) scale(6)" style="stroke:var(--vl-color-accent)" '
        'fill="none" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
        f"{icon_body('package')}</g>"
    )

    assert picture_body("package", "accent", 3) == expected


@pytest.mark.parametrize("tone", PICTURE_TONES)
def test_every_tone_paints_the_picture_with_its_base_colour(tone: str) -> None:
    base = PICTURE_COLOURS[tone]
    body = picture_body("image", tone, 1)
    group = f'<g transform="translate(128 78) scale(6)" style="stroke:var(--vl-color-{base})" '

    assert re.findall(r"var\(--vl-color-([a-z-]+)\)", body) == [base, "surface", base]
    assert body.startswith(
        '<rect width="400" height="300" style="fill:color-mix(in srgb, '
        f'var(--vl-color-{base}) 14%, var(--vl-color-surface))"></rect>{group}'
    )
    assert set(re.findall(r"var\((--vl-color-[a-z-]+)\)", body)) <= TOKEN_NAMES
    assert body.endswith(icon_body("image") + "</g>")


@pytest.mark.parametrize("index", [1, 2, 17])
def test_a_picture_is_the_same_flat_drawing_at_every_index(index: int) -> None:
    assert picture_body("image", "neutral", index) == picture_body("image", "neutral", 1)


def test_no_picture_carries_a_gradient_a_definition_an_identifier_or_a_reference() -> None:
    for name in icon_names():
        drawing = icon_body(name)
        for tone in PICTURE_TONES:
            body = picture_body(name, tone, 1)
            frame = body.replace(drawing, "")

            assert "gradient" not in body.lower(), (name, tone)
            assert body.endswith(f"{drawing}</g>"), (name, tone)
            for absent in ("<defs", "<stop", "<circle", "url(", " id=", "opacity"):
                assert absent not in frame, (name, tone, absent)
            assert (frame.count("<rect "), frame.count("<g ")) == (1, 1), (name, tone)


def test_a_picture_needs_a_known_icon_a_known_tone_and_a_positive_index() -> None:
    with pytest.raises(KeyError):
        picture_body("pacco", "primary", 1)
    with pytest.raises(KeyError):
        picture_body("package", "blue", 1)
    for index in (0, -1, True, 1.0, "1"):
        with pytest.raises(ValueError):
            picture_body("package", "primary", index)


def test_the_resources_of_the_model_name_every_icon_and_every_tone() -> None:
    resources = mockup_resources()

    assert resources == {"icons": list(icon_names()), "tones": list(PICTURE_TONES)}
    assert json.loads(json.dumps(resources)) == resources
    resources["icons"].clear()
    resources["tones"].append("other")
    assert mockup_resources() == {"icons": list(icon_names()), "tones": list(PICTURE_TONES)}
