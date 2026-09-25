"""Isolated Docker checks: no host ports, production state or credentials."""
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
FUNCTION = re.search(
    r"^frontend_asset_healthcheck\(\) \{\n.*?^\}",
    (ROOT / 'deploy/dpms-node.sh').read_text(), re.M | re.S,
).group(0)
LOCATION = re.search(
    r"    location ~ \^/graph-workspace/.*?\n    \}",
    (ROOT / 'deploy/nginx.conf').read_text(), re.S,
).group(0)


class GraphModuleHealthTests(unittest.TestCase):
    def health(self, response='200 application/javascript', missing='404', legacy=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            graph = root / 'frontend/dist/graph-workspace'
            graph.mkdir(parents=True)
            (graph / 'index.html').write_text('legacy' if legacy else 'connection-ports.mjs')
            script = '''
DPMS_DOMAIN_PUNY=example.invalid
DPMS_LIVE_ROOT=/fixture
curl() {
  case "${@: -1}" in
    */dpms-healthcheck-missing.mjs) printf '%s' "$MODULE_MISSING" ;;
    */dpms-healthcheck-missing.js) printf '404' ;;
    *.mjs) printf '%s' "$MODULE_RESPONSE" ;;
    */assets/test.js) printf '200 application/javascript' ;;
    *) printf '<script src="/assets/test.js"></script>' ;;
  esac
}
''' + FUNCTION + '\nfrontend_asset_healthcheck\n'
            result = subprocess.run([
                'docker', 'run', '--rm', '--network', 'none', '-i',
                '-v', temp + ':/fixture:ro', '-e', 'MODULE_RESPONSE=' + response,
                '-e', 'MODULE_MISSING=' + missing, 'python:3.11-slim',
                '/bin/sh', '-c', 'exec /bin/bash -s',
            ], input=script, text=True, capture_output=True)
            self.assertNotIn(result.returncode, (125, 126, 127), result.stderr)
            return result

    def test_modules_have_javascript_mime(self):
        result = self.health()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_octet_stream_is_rejected(self):
        self.assertNotEqual(self.health('200 application/octet-stream').returncode, 0)

    def test_missing_module_is_rejected(self):
        self.assertNotEqual(self.health('404 text/html').returncode, 0)

    def test_spa_fallback_for_missing_module_is_rejected(self):
        self.assertNotEqual(self.health(missing='200').returncode, 0)

    def test_old_release_without_modules_remains_checkable(self):
        result = self.health('404 text/html', '200', legacy=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class GraphModuleNginxTests(unittest.TestCase):
    def test_real_nginx_module_headers_and_missing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'nginx.conf').write_text(
                'events {}\nhttp { include /etc/nginx/mime.types; '
                'default_type application/octet-stream; server { listen 80; '
                'root /web; add_header X-Content-Type-Options nosniff always;\n'
                + LOCATION + '\nlocation / { try_files $uri /index.html; } } }\n'
            )
            (root / 'index.html').write_text('SPA fallback')
            (root / 'graph-workspace').mkdir()
            name = 'dpms-graph-mime-' + uuid4().hex[:10]
            subprocess.run([
                'docker', 'run', '--rm', '-d', '--network', 'none', '--name', name,
                '-v', temp + ':/web:ro',
                '-v', str(ROOT / 'frontend/public/graph-workspace') + ':/web/graph-workspace:ro',
                'nginx:1.27-alpine', 'nginx', '-c', '/web/nginx.conf', '-g', 'daemon off;',
            ], check=True, capture_output=True)
            try:
                for attempt in range(30):
                    ready = subprocess.run([
                        'docker', 'exec', name, 'wget', '-q', '-O', '/dev/null',
                        'http://127.0.0.1/',
                    ], capture_output=True)
                    if ready.returncode == 0:
                        break
                    time.sleep(0.1)
                self.assertEqual(ready.returncode, 0, ready.stderr)
                for module in ('connection-ports', 'edge-routing', 'import-adapters'):
                    result = subprocess.run([
                        'docker', 'exec', name, 'wget', '-S', '-O', '/dev/null',
                        'http://127.0.0.1/graph-workspace/' + module + '.mjs',
                    ], text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('Content-Type: application/javascript', result.stderr)
                    self.assertIn('Cache-Control: no-cache', result.stderr)
                    self.assertIn('X-Content-Type-Options: nosniff', result.stderr)
                missing = subprocess.run([
                    'docker', 'exec', name, 'wget', '-S', '-O', '/dev/null',
                    'http://127.0.0.1/graph-workspace/missing.mjs',
                ], text=True, capture_output=True)
                self.assertNotEqual(missing.returncode, 0)
                self.assertIn('404 Not Found', missing.stderr)
            finally:
                subprocess.run(['docker', 'stop', '-t', '3', name], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
