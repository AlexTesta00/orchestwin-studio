<?php
declare(strict_types=1);
require_once __DIR__ . '/../src/Counter.php';
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="/style.css">
  <title>PHP counter</title>
</head>
<body>
  <main><h1>PHP counter</h1><p>Incrementing zero produces <output id="count"><?= increment(0) ?></output>.</p></main>

</body>
</html>
