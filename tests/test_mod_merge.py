"""Unit tests for XSD-driven *Mod merge field filtering."""

from qbwc_common.mod_merge import (
    filter_dict_for_mod,
    get_mod_element_names,
    get_ret_only_field_names,
)
from qbwc_common.qbxml import load_qbd_xml_schemas

SCHEMA = load_qbd_xml_schemas()


def test_get_mod_element_names_includes_identity_and_excludes_ret_only_fields():
    """CustomerMod allowlist includes ListID and excludes Balance from CustomerRet."""
    allowed = get_mod_element_names(SCHEMA, "CustomerMod")

    assert "ListID" in allowed
    assert "EditSequence" in allowed
    assert "CompanyName" in allowed
    assert "Balance" not in allowed
    assert "FullName" not in allowed
    assert "TimeCreated" not in allowed


def test_get_ret_only_field_names_matches_ret_minus_mod():
    """Ret-only names are top-level Ret fields absent from the matching Mod element."""
    ret_only = get_ret_only_field_names(SCHEMA, "CustomerRet", "CustomerMod")
    mod_names = get_mod_element_names(SCHEMA, "CustomerMod")

    assert "Balance" in ret_only
    assert "FullName" in ret_only
    assert "ListID" not in ret_only
    assert ret_only.isdisjoint(mod_names)


def test_get_mod_element_names_caches_results():
    """Return the same frozenset object for repeated lookups of one mod element."""
    first = get_mod_element_names(SCHEMA, "CustomerMod")
    second = get_mod_element_names(SCHEMA, "CustomerMod")

    assert first is second


def test_filter_dict_for_mod_keeps_allowed_top_level_keys():
    """Drop Ret-only keys and keep Mod-valid keys at the top level."""
    allowed = get_mod_element_names(SCHEMA, "CustomerMod")
    payload = {
        "ListID": "80002754-1786031476",
        "Balance": "0.00",
        "FullName": "HG-TGT-E2E-001",
        "CompanyName": "Updated Company",
    }

    filtered = filter_dict_for_mod(payload, allowed)

    assert filtered == {
        "ListID": "80002754-1786031476",
        "CompanyName": "Updated Company",
    }


def test_invoice_mod_excludes_txn_computed_fields():
    """InvoiceMod drops txn balances and line Ret arrays from queried InvoiceRet."""
    allowed = get_mod_element_names(SCHEMA, "InvoiceMod")

    assert "TxnID" in allowed
    assert "RefNumber" in allowed
    assert "TxnNumber" not in allowed
    assert "BalanceRemaining" not in allowed
    assert "ItemLineRet" not in allowed
    assert "InvoiceLineMod" in allowed


def test_journal_entry_mod_excludes_memo():
    """JournalEntryMod does not define Memo even though JournalEntryRet returns it."""
    allowed = get_mod_element_names(SCHEMA, "JournalEntryMod")

    assert "TxnID" in allowed
    assert "Memo" not in allowed
    assert "JournalLineMod" in allowed


def test_item_noninventory_mod_uses_mod_block_names():
    """ItemNonInventoryMod uses SalesOrPurchaseMod, not SalesOrPurchase from Ret."""
    allowed = get_mod_element_names(SCHEMA, "ItemNonInventoryMod")

    assert "SalesOrPurchase" not in allowed
    assert "SalesOrPurchaseMod" in allowed
    assert "ManufacturerPartNumber" in allowed


def test_representative_ret_only_fields_are_not_on_mod_allowlist():
    """Known Ret-only fields from step 4 e2e are absent from the Mod allowlist."""
    cases = [
        ("CustomerMod", ["Balance", "FullName", "TimeCreated", "ContactsRet"]),
        ("ItemInventoryMod", ["QuantityOnHand", "SalesOrPurchase", "AverageCost"]),
        ("InvoiceMod", ["TxnNumber", "BalanceRemaining", "ItemLineRet", "CurrencyRef"]),
        ("JournalEntryMod", ["Memo", "JournalDebitLine", "TxnNumber"]),
    ]

    for mod_name, ret_only_fields in cases:
        allowed = get_mod_element_names(SCHEMA, mod_name)
        still_allowed = [field for field in ret_only_fields if field in allowed]
        assert not still_allowed, f"{mod_name}: Ret-only fields on Mod: {still_allowed}"

