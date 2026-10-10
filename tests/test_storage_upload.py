"""Storage errors must not hide a missing private bucket or expose provider data."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import supabase_client as storage


def error(status, body):
    return HTTPError('https://example.test/storage', status, 'error', {},
                     io.BytesIO(json.dumps(body).encode()))


class StorageUpload(unittest.TestCase):
    def setUp(self):
        self.settings = patch.multiple(storage, SUPABASE_URL='https://example.test',
                                       SUPABASE_KEY='public-test', SUPABASE_SERVICE_KEY='server-test')
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def test_missing_bucket_is_created_private_before_retry(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{}'
        with patch.object(storage.urllib.request, 'urlopen', side_effect=[
            error(400, {'message':'Bucket not found'}), response]) as opening, \
             patch.object(storage, 'request') as create:
            storage.upload_file('course-files', 'attachments/test.png', b'png', 'image/png')
            create.assert_called_once_with('/storage/v1/bucket', 'POST', {
                'id':'course-files', 'name':'course-files', 'public':False, 'file_size_limit':10485760})
            self.assertEqual(opening.call_count, 2)

    def test_permission_error_is_safe_and_does_not_create_bucket(self):
        with patch.object(storage.urllib.request, 'urlopen', side_effect=error(
            403, {'message':'private provider details', 'code':'AccessDenied'})), \
             patch.object(storage, 'request') as create:
            with self.assertRaisesRegex(ValueError, 'Supabase refuse le dépôt'):
                storage.upload_file('course-files', 'attachments/test.png', b'png')
            create.assert_not_called()

    def test_bucket_creation_failure_is_reported(self):
        with patch.object(storage.urllib.request, 'urlopen', side_effect=error(
            400, {'message':'Bucket not found'})), \
             patch.object(storage, 'request', side_effect=error(403, {})):
            with self.assertRaisesRegex(ValueError, 'ne peut pas être initialisé'):
                storage.upload_file('course-files', 'attachments/test.png', b'png')


if __name__ == '__main__':
    unittest.main()
