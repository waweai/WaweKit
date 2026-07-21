"""Tests for the reusable fingerprint options widget (headless, offscreen Qt).

These moved here from ``test_fingerprint_dialog`` in Module 7, when the controls
were extracted so the similarity dialog could reuse them. The tests follow the
behaviour, not the file it used to live in.
"""

from __future__ import annotations

from wawekit.gui.widgets.fingerprint_options import FingerprintOptionsWidget
from wawekit.models.fingerprints import MACCS_N_BITS, FingerprintKind, FingerprintOptions


def _select(widget: FingerprintOptionsWidget, kind: FingerprintKind) -> None:
    widget._kind.setCurrentIndex(widget._kind.findData(kind))


def test_defaults_are_morgan_r2_2048(qtbot):
    widget = FingerprintOptionsWidget()
    qtbot.addWidget(widget)
    options = widget.options()
    assert options.kind is FingerprintKind.MORGAN
    assert options.radius == 2
    assert options.n_bits == 2048
    assert options.use_features is False


def test_selected_kind_is_a_real_enum_member_not_a_string(qtbot):
    """Regression: StrEnum item data returns a plain str after a QVariant trip.

    Qt stores combo item data in a QVariant. Because FingerprintKind is a
    StrEnum (and therefore a str), the round-trip yields a plain ``str``, so
    ``is`` comparisons against enum members silently fail and the dialog
    reported Morgan whatever the user chose. The widget must coerce it back.
    """
    widget = FingerprintOptionsWidget()
    qtbot.addWidget(widget)
    for kind in FingerprintKind:
        _select(widget, kind)
        selected = widget.options().kind
        assert type(selected) is FingerprintKind
        assert selected is kind


def test_morgan_enables_every_parameter(qtbot):
    widget = FingerprintOptionsWidget()
    qtbot.addWidget(widget)
    _select(widget, FingerprintKind.MORGAN)
    assert widget._radius.isEnabled()
    assert widget._bits.isEnabled()
    assert widget._features.isEnabled()


def test_maccs_disables_every_parameter(qtbot):
    # MACCS is a fixed key set: radius, bit size and features are meaningless.
    widget = FingerprintOptionsWidget()
    qtbot.addWidget(widget)
    _select(widget, FingerprintKind.MACCS)
    assert not widget._radius.isEnabled()
    assert not widget._bits.isEnabled()
    assert not widget._features.isEnabled()


def test_rdkit_enables_only_bit_size(qtbot):
    widget = FingerprintOptionsWidget()
    qtbot.addWidget(widget)
    _select(widget, FingerprintKind.RDKIT)
    assert not widget._radius.isEnabled()
    assert widget._bits.isEnabled()
    assert not widget._features.isEnabled()


def test_widget_values_reach_the_options(qtbot):
    widget = FingerprintOptionsWidget()
    qtbot.addWidget(widget)
    _select(widget, FingerprintKind.MORGAN)
    widget._radius.setValue(3)
    widget._bits.setCurrentIndex(widget._bits.findData(1024))
    widget._features.setChecked(True)

    options = widget.options()
    assert options.radius == 3
    assert options.n_bits == 1024
    assert options.use_features is True
    assert options.label == "FCFP r3 · 1024b"


# ------------------------------------------------------------- set_options
def test_set_options_round_trips(qtbot):
    widget = FingerprintOptionsWidget()
    qtbot.addWidget(widget)
    wanted = FingerprintOptions(radius=4, n_bits=4096, use_features=True)
    widget.set_options(wanted)
    assert widget.options() == wanted


def test_set_options_syncs_the_enabled_state(qtbot):
    widget = FingerprintOptionsWidget()
    qtbot.addWidget(widget)
    widget.set_options(FingerprintOptions(kind=FingerprintKind.MACCS))
    assert not widget._radius.isEnabled()
    assert not widget._bits.isEnabled()


def test_set_options_tolerates_normalized_maccs_bit_count(qtbot):
    # A normalized MACCS options object reports 167 bits, which is not one of
    # the offered sizes. That must not throw or blank the combo.
    widget = FingerprintOptionsWidget()
    qtbot.addWidget(widget)
    normalized = FingerprintOptions(kind=FingerprintKind.MACCS).normalized()
    assert normalized.n_bits == MACCS_N_BITS
    widget.set_options(normalized)
    assert widget.options().kind is FingerprintKind.MACCS
    assert widget._bits.currentData() in (1024, 2048, 4096)
