<?php
declare(strict_types=1);
use PHPUnit\Framework\TestCase;
require_once __DIR__ . '/../../backend/admin-operations.php';

final class AdminOperationsHandlerTest extends TestCase
{
    public function testAnonymousRequestCannotReachDatabaseOrBackend(): void
    {
        $security = $this->createStub(ISecurityHelper::class);
        $security->method('validateSession')->willReturn(false);
        $database = $this->createMock(IDatabaseHelper::class);
        $database->expects($this->never())->method('getPDO');
        $backend = $this->createMock(ICurlHelper::class);
        $backend->expects($this->never())->method('makeBackendRequest');
        $handler = new AdminOperationsHandler($security, $database, $backend, $this->createStub(IAuthHelper::class));
        $this->expectExceptionCode(401);
        $handler->response('GET');
    }

    public function testStudentCannotReachBackend(): void
    {
        $security = $this->createStub(ISecurityHelper::class);
        $security->method('validateSession')->willReturn(true);
        $security->method('validateAdminAccess')->willReturn(false);
        $database = $this->createStub(IDatabaseHelper::class);
        $database->method('getPDO')->willReturn($this->createStub(PDO::class));
        $backend = $this->createMock(ICurlHelper::class);
        $backend->expects($this->never())->method('makeBackendRequest');
        $handler = new AdminOperationsHandler($security, $database, $backend, $this->createStub(IAuthHelper::class));
        $this->expectExceptionCode(403);
        $handler->response('GET');
    }

    public function testMutationIsRejectedBeforeSessionOrBackendAccess(): void
    {
        $security = $this->createMock(ISecurityHelper::class);
        $security->expects($this->never())->method('initSecureSession');
        $handler = new AdminOperationsHandler($security, $this->createStub(IDatabaseHelper::class), $this->createStub(ICurlHelper::class), $this->createStub(IAuthHelper::class));
        $this->expectExceptionCode(405);
        $handler->response('POST');
    }

    public function testAdministratorGetsOnlyDocumentedTopLevelFields(): void
    {
        $security = $this->createStub(ISecurityHelper::class);
        $security->method('validateSession')->willReturn(true);
        $security->method('validateAdminAccess')->willReturn(true);
        $database = $this->createStub(IDatabaseHelper::class);
        $database->method('getPDO')->willReturn($this->createStub(PDO::class));
        $auth = $this->createStub(IAuthHelper::class);
        $auth->method('getBackendHeaders')->willReturn(['private-token-header']);
        $backend = $this->createMock(ICurlHelper::class);
        $backend->expects($this->once())->method('makeBackendRequest')->with('/admin/operations', 'GET', ['private-token-header'])->willReturn([
            'success' => true, 'response' => json_encode(['success' => true, 'data' => ['database' => 'ready', 'private_secret' => 'must-not-return']])
        ]);
        $result = (new AdminOperationsHandler($security, $database, $backend, $auth))->response('GET');
        $this->assertSame(['success' => true, 'data' => ['database' => 'ready']], $result);
    }
}
