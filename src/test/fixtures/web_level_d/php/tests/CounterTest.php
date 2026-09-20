<?php
declare(strict_types=1);

use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../src/Counter.php';

final class CounterTest extends TestCase
{
    public function testIncrementAdvancesByExactlyOne(): void
    {
        self::assertSame(1, increment(0), 'LEVEL_D_NEGATIVE_CONTROL');
        self::assertSame(42, increment(41), 'LEVEL_D_NEGATIVE_CONTROL');
    }

    public function testPublicPageRendersTheCalculatedValue(): void
    {
        ob_start();
        try {
            require __DIR__ . '/../public/index.php';
            $html = ob_get_contents();
        } finally {
            ob_end_clean();
        }
        self::assertIsString($html);
        self::assertStringContainsString('<output id="count">1</output>', $html);
        self::assertStringContainsString('<html lang="en">', $html);
    }
}
