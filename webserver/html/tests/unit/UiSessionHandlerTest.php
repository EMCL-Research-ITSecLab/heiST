<?php
declare(strict_types=1);

use PHPUnit\Framework\TestCase;
require_once __DIR__ . '/../../backend/session.php';

final class UiSessionHandlerTest extends TestCase
{
    private function security(bool $authenticated, bool $reset = false): SecurityHelper
    {
        $security = $this->createStub(SecurityHelper::class);
        $security->method('validateSession')->willReturn($authenticated);
        $security->method('validateCsrfToken')->willReturn(true);
        $security->method('generateCsrfToken')->willReturn(str_repeat('b', 64));
        $security->method('requiresPasswordChange')->willReturn($reset);
        return $security;
    }

    public function testGuestBootstrapDoesNotConnectToTheDatabase(): void
    {
        $session = new MockSession();
        $session['csrf_token'] = str_repeat('a', 64);
        $database = $this->createMock(IDatabaseHelper::class);
        $database->expects($this->never())->method('getPDO');
        $result = (new UiSessionHandler($this->security(false), $session, $database))->response();
        $this->assertTrue($result['success']);
        $this->assertFalse($result['data']['is_logged_in']);
        $this->assertNull($result['data']['user']);
        $this->assertSame(str_repeat('a', 64), $result['data']['csrf_token']);
    }

    public function testBootstrapCreatesMissingCsrfToken(): void
    {
        $result = (new UiSessionHandler($this->security(false), new MockSession(), $this->createStub(IDatabaseHelper::class)))->response();
        $this->assertSame(str_repeat('b', 64), $result['data']['csrf_token']);
    }

    private function authenticatedResult(array|false $record, bool $reset = false): array
    {
        $session = new MockSession();
        $session['user_id'] = 42;
        $session['username'] = 'investigator';
        $session['csrf_token'] = str_repeat('a', 64);
        $statement = $this->createMock(PDOStatement::class);
        $statement->expects($this->once())->method('execute')->with(['user_id' => 42])->willReturn(true);
        $statement->method('fetch')->willReturn($record);
        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->willReturn($statement);
        $database = $this->createStub(IDatabaseHelper::class);
        $database->method('getPDO')->willReturn($pdo);
        return (new UiSessionHandler($this->security(true, $reset), $session, $database))->response();
    }

    public function testAdministratorAndForcedResetAreReportedWithoutPrivateFields(): void
    {
        $result = $this->authenticatedResult(['avatar_url' => '/assets/avatars/default.png', 'is_admin' => 't', 'password' => 'never expose', 'api_token' => 'never expose'], true);
        $this->assertTrue($result['data']['requires_password_change']);
        $this->assertTrue($result['data']['user']['is_admin']);
        $this->assertSame(['username', 'avatar_url', 'is_admin'], array_keys($result['data']['user']));
        $this->assertSame('investigator', $result['data']['user']['username']);
    }

    public function testPostgresFalseDoesNotBecomeAnAdministrator(): void
    {
        $result = $this->authenticatedResult(['avatar_url' => '', 'is_admin' => 'f']);
        $this->assertFalse($result['data']['user']['is_admin']);
        $this->assertFalse($result['data']['requires_password_change']);
    }

    public function testDeletedAccountFailsClosed(): void
    {
        $this->expectException(RuntimeException::class);
        $this->authenticatedResult(false);
    }
}
