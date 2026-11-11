import contextlib
import importlib.util
import io
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("isp_dns", Path(__file__).parents[1] / "ispmanager-dns.py")
dns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dns)
TOKEN = "A" * 43


class DnsHookTest(unittest.TestCase):
    def test_cleanup_preserves_other_values_names_and_types(self):
        client = Mock()
        client.records.return_value = [
            dict(name=dns.CHALLENGE + ".", rtype="TXT", value='"' + TOKEN + '"', rkey="ours"),
            dict(name=dns.CHALLENGE, rtype="TXT", value="another-challenge", rkey="other"),
            dict(name="mail.codoc.site", rtype="TXT", value=TOKEN, rkey="mail"),
            dict(name=dns.CHALLENGE, rtype="A", value=TOKEN, rkey="address"),
        ]
        dns.remove(client, TOKEN)
        client.call.assert_called_once_with("domain.record.delete", plid=dns.DOMAIN, elid="ours", sok="ok")

    def test_existing_record_is_never_created_again(self):
        client = Mock()
        client.records.return_value = [dict(name=dns.CHALLENGE, rtype="TXT", value=TOKEN)]
        self.assertFalse(dns.add(client, TOKEN))
        client.call.assert_not_called()

    def test_propagation_failure_cleans_up_our_record(self):
        client = Mock()
        with patch.object(dns, "add", return_value=True), patch.object(dns, "wait_for_dns", side_effect=RuntimeError), patch.object(dns, "remove") as remove:
            with self.assertRaises(RuntimeError):
                dns.authenticate(client, TOKEN)
            remove.assert_called_once_with(client, TOKEN)

    def test_propagation_failure_preserves_preexisting_record(self):
        with patch.object(dns, "add", return_value=False), patch.object(dns, "wait_for_dns", side_effect=RuntimeError), patch.object(dns, "remove") as remove:
            with self.assertRaises(RuntimeError):
                dns.authenticate(Mock(), TOKEN)
            remove.assert_not_called()

    def test_cleanup_refuses_to_guess_missing_record_identifier(self):
        client = Mock()
        client.records.return_value = [dict(name=dns.CHALLENGE, rtype="TXT", value=TOKEN)]
        with self.assertRaises(RuntimeError):
            dns.remove(client, TOKEN)
        client.call.assert_not_called()

    def test_hook_rejects_other_domains(self):
        with patch.dict(os.environ, CERTBOT_DOMAIN="example.com", CERTBOT_VALIDATION=TOKEN):
            with self.assertRaises(RuntimeError):
                dns.challenge_value()

    def test_hook_requires_exact_dns_token_not_a_substring(self):
        with patch.object(dns.subprocess, "run", return_value=Mock(returncode=0, stdout='"prefix' + TOKEN + '"\n')):
            self.assertFalse(dns.visible("8.8.8.8", TOKEN))

    def test_preexisting_record_is_marked_for_preservation(self):
        output = io.StringIO()
        with patch.object(dns, "add", return_value=False), patch.object(dns, "wait_for_dns"), contextlib.redirect_stdout(output):
            dns.authenticate(Mock(), TOKEN)
        self.assertEqual(output.getvalue().strip(), '{"created": false}')


if __name__ == "__main__":
    unittest.main()
