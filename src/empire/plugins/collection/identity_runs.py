"""Identity operations use the shared bounded Redis diagnostics, never SQL history."""
import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4


class IdentityRuns:
    def __init__(self, records, platform):
        self.records, self.platform = records, platform
        self.active = {}
        self.error = ''

    @asynccontextmanager
    async def operation(self, code, operation):
        row = dict(id=uuid4().hex, code=code, operation=operation, status='running',
                   started_at=datetime.now(UTC).isoformat(), finished_at=None,
                   stage=operation, error_code=None, message='正在执行')
        if self.records is not None:
            # Do not issue a request when its initial diagnostic intent cannot be saved.
            await self.records.add_identity_run(self.platform, row)
        self.active[row['id']] = dict(row)
        try:
            yield
            row.update(status='success', message='执行成功')
        except asyncio.CancelledError:
            row.update(status='interrupted', message='操作已取消，申请结果以持久状态为准')
            raise
        except Exception as exc:
            error_code = getattr(exc, 'code', None)
            row.update(status='failed', message='申请或登录失败；检查阶段、错误码和身份状态',
                       error_code=error_code if type(error_code) is int else None)
            stage = getattr(exc, 'stage', None)
            if stage in {'guest-application', 'public-key', 'public-key-format', 'login',
                         'session-format', 'passport', 'passport-format', 'native-login', 'native-login-size'}:
                row['stage'] = stage
            raise
        finally:
            row['finished_at'] = datetime.now(UTC).isoformat()
            try:
                if self.records is not None:
                    await self.records.add_identity_run(self.platform, row)
                self.error = ''
            except Exception:
                self.error = '运行结果写入Redis失败，历史记录可能未确认；不会重新申请账号'
            finally:
                self.active.pop(row['id'], None)
