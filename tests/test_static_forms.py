"""Static checks for form status regions, invalid-field handling and form control markup."""

import re

from tests.frontend import HTML, JS, HTMLDocument, js_function


def test_status_containers_keep_polite_defaults():
    for node_id in ("status", "geo-status", "chat-status"):
        tag = re.search(r'<div\b[^>]*\bid="' + node_id + r'"[^>]*>', HTML)
        assert tag, node_id
        assert 'role="status"' in tag.group(0), node_id
        assert 'aria-live="polite"' in tag.group(0), node_id


def test_set_status_switches_role_and_live_region():
    body = js_function("setStatus")
    assert re.search(
        r'setAttribute\(\s*"role"\s*,\s*opts\.error\s*\?\s*"alert"\s*:\s*"status"', body
    )
    assert re.search(
        r'setAttribute\(\s*"aria-live"\s*,\s*opts\.error\s*\?\s*"assertive"\s*:\s*"polite"', body
    )
    # The same node is reused, and the role is set before the text is written.
    assert "createElement" not in body
    assert "replaceChild" not in body
    assert body.index('"role"') < body.index("clearNode(node)") < body.index("appendChild")


def test_invalid_fields_set_aria_invalid_and_append_describedby():
    mark = js_function("markInvalid")
    assert 'setAttribute("aria-invalid", "true")' in mark
    assert 'tokens(control, "aria-describedby")' in mark
    assert "indexOf(statusId) < 0" in mark  # appended once, never clobbered
    assert 'setAttribute("aria-describedby"' in mark
    unmark = js_function("unmarkInvalid")
    assert 'removeAttribute("aria-invalid")' in unmark
    assert 'removeAttribute("aria-describedby")' in unmark
    assert "t !== statusId" in unmark  # only our own id is removed


def test_invalid_marks_cleared_on_new_status_and_when_field_fixed():
    assert "clearInvalidFields()" in js_function("setStatus")
    assert "unmarkInvalid(" in js_function("revalidateControl")
    init = js_function("init")
    assert "revalidateControl(id)" in init
    assert '"change"' in init and '"input"' in init


def test_api_field_names_map_to_controls_or_are_skipped():
    body = js_function("controlIdForApiField")
    assert 'split(".")' in body  # "profile.kids" -> "kids"
    assert ": null;" in body  # unmappable names yield null and are skipped
    assert "describeError" in JS and "fields: Array.isArray(err.fields)" in JS


def test_focus_moves_to_first_invalid_field_on_validation_failure():
    focus = js_function("focusControl")
    assert ".focus()" in focus
    ids = js_function("markInvalidIds")
    assert "controlIds().forEach" in ids  # form order decides which is first
    submit = js_function("onGenerate")
    client = submit.index("invalidFields(profile)")
    assert client < submit.index("focusControl(markInvalidIds(")
    assert re.search(
        r'code\s*===\s*"validation_error"\s*\)\s*\{\s*focusControl\(markApiFields', submit
    )
    # Focus is moved only for validation failures, not for success or other errors.
    assert submit.count("focusControl(") == 2


def test_geolocation_errors_do_not_move_focus():
    assert "focus" not in js_function("onUseLocation").lower()


def test_geolocation_timer_is_cleared_once_a_position_arrives():
    body = js_function("onUseLocation")
    success = body[body.index("getCurrentPosition(function (pos)") :]
    # The timeout must not fire during the AQI lookup that follows a position.
    assert success.index("clearTimeout(timer)") < success.index("callApi(")


def test_form_controls_have_associated_labels():
    doc = HTMLDocument(HTML)
    label_for_targets = {
        label.attrs["for"] for label in doc.find_all("label") if "for" in label.attrs
    }

    # All input/select elements in index.html must have an associated <label for>
    form_controls = doc.find_all("input") + doc.find_all("select")
    assert form_controls, "expected form controls in index.html"
    for control in form_controls:
        control_id = control.attrs.get("id")
        assert control_id, f"<{control.tag}> control is missing an id: {control.attrs}"
        assert control_id in label_for_targets, (
            f"<{control.tag} id='{control_id}'> has no matching <label for='{control_id}'>"
        )

    # Dynamic fields generated in app.js: buildForm assigns matching label.htmlFor and select.id
    build_form = js_function("buildForm")
    assert 'label.htmlFor = "f-" + f.name;' in build_form
    assert 'select.id = "f-" + f.name;' in build_form
    assert "wrap.appendChild(label);" in build_form
    assert "wrap.appendChild(select);" in build_form


def test_button_elements_have_explicit_type():
    doc = HTMLDocument(HTML)
    buttons = doc.find_all("button")
    assert len(buttons) >= 4, "expected at least 4 buttons in index.html"
    for btn in buttons:
        btn_type = btn.attrs.get("type")
        assert btn_type in {"button", "submit", "reset"}, (
            f"<button id='{btn.attrs.get('id')}'> is missing explicit type: {btn.attrs}"
        )

    # Dynamically generated starter buttons in buildChat must set explicit type="button"
    build_chat = js_function("buildChat")
    assert 'b.type = "button";' in build_chat
