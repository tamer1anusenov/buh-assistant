from accounting_assistant.frontend.utils import safe_filename, validate_uploads


def test_frontend_upload_validation():
    errors = validate_uploads([("receipt.txt", 12), ("receipt.pdf", 12), ("empty.txt", 0)])
    assert any("только TXT" in error for error in errors)
    assert any("пуст" in error for error in errors)


def test_frontend_filename_is_safely_reduced_to_basename():
    assert safe_filename("../../receipt.txt") == "receipt.txt"
