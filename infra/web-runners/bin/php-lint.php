<?php

declare(strict_types=1);

$root = $argv[1] ?? '.';
$iterator = new RecursiveIteratorIterator(
    new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS)
);
$failed = false;
foreach ($iterator as $file) {
    if (!$file->isFile() || strtolower($file->getExtension()) !== 'php') {
        continue;
    }
    $process = proc_open(
        ['php', '-l', $file->getPathname()],
        [1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
        $pipes
    );
    if (!is_resource($process)) {
        fwrite(STDERR, "Unable to start PHP lint.\n");
        exit(2);
    }
    $stdout = stream_get_contents($pipes[1]);
    $stderr = stream_get_contents($pipes[2]);
    fclose($pipes[1]);
    fclose($pipes[2]);
    $exitCode = proc_close($process);
    fwrite(STDOUT, $stdout);
    fwrite(STDERR, $stderr);
    if ($exitCode !== 0) {
        $failed = true;
    }
}
exit($failed ? 1 : 0);
