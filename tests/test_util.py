from reelbot.util import canonical_url, domain_matches, slugify


def test_url_canonicalization_and_domain_safety():
    assert canonical_url("HTTPS://NASA.GOV/a/?utm_source=x") == "https://nasa.gov/a"
    assert domain_matches("science.nasa.gov", ["nasa.gov"])
    assert not domain_matches("nasa.gov.example.org", ["nasa.gov"])


def test_slugify_is_filename_safe():
    assert slugify("A New Discovery: 100% Interesting!") == "a-new-discovery-100-interesting"

