import unittest
from unittest.mock import MagicMock, patch
from leadhunter import report_recovery
from leadhunter.core import emit_discovery_summary


class ReportRecoveryTests(unittest.TestCase):
    def test_recovers_without_smtp_or_source_access_and_closes_connection(self):
        db = MagicMock()
        store = MagicMock()
        store.pending_reports.return_value = []
        with patch.object(report_recovery, 'connect_private_database', return_value=db), patch.object(
            report_recovery, 'AutoMailStore', return_value=store), patch.object(
            report_recovery, 'flush_reports', side_effect=[5, 2, 0]), patch(
            'leadhunter.automatic_mail.send_mail', side_effect=AssertionError('SMTP forbidden')), patch(
            'leadhunter.core.get_osm', side_effect=AssertionError('OSM forbidden')):
            self.assertEqual(report_recovery.run({'TELEGRAM_BOT_TOKEN':'fixture',
                'TELEGRAM_CHAT_ID':'123','REVIEW_DATABASE_URL':'fixture'}, output=lambda _:None), 7)
        db.close.assert_called_once()

    def test_report_failure_stops_processing_and_closes_connection(self):
        db = MagicMock()
        with patch.object(report_recovery, 'connect_private_database', return_value=db), patch.object(
            report_recovery, 'flush_reports', side_effect=RuntimeError('report failed')):
            with self.assertRaisesRegex(RuntimeError, 'report failed'):
                report_recovery.run({'TELEGRAM_BOT_TOKEN':'fixture','TELEGRAM_CHAT_ID':'123'})
        db.close.assert_called_once()

    def test_backlog_drain_is_bounded(self):
        db = MagicMock()
        store = MagicMock()
        store.pending_reports.return_value = [('node/1', {})]
        with patch.object(report_recovery, 'AutoMailStore', return_value=store), patch.object(
            report_recovery, 'connect_private_database', return_value=db), patch.object(
            report_recovery, 'flush_reports', return_value=5) as flush:
            with self.assertRaisesRegex(RuntimeError, 'backlog remains'):
                report_recovery.run({'TELEGRAM_BOT_TOKEN':'fixture','TELEGRAM_CHAT_ID':'123'})
        self.assertEqual(flush.call_count, 20)
        db.close.assert_called_once()

    def test_mail_report_count_is_not_called_new_opportunities(self):
        output = []
        emit_discovery_summary(dict(fetched=20,eligible=20,rejected=0,duplicates=0,
            already_seen=20,new=0), 5, {'AUTO_MAIL_ENABLED':'true'}, output.append)
        self.assertIn('Telegram mail sonuç raporu: 5', output)
        self.assertFalse(any('Gönderilen yeni fırsat: 5' in line for line in output))
