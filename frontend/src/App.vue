<template>
  <div class="application-shell">
    <a class="skip-link" href="#main-content">Skip to main content</a>

    <header class="site-header">
      <RouterLink class="brand" to="/" aria-label="OrchesTwin Studio home">
        OrchesTwin Studio
      </RouterLink>

      <nav class="primary-navigation" aria-label="Primary navigation">
        <RouterLink class="primary-navigation__link" data-testid="overview-link" to="/">
          Overview
        </RouterLink>

        <RouterLink class="primary-navigation__link" data-testid="projects-link" to="/projects">
          Projects
        </RouterLink>
      </nav>
    </header>

    <main id="main-content" class="main-content" tabindex="-1">
      <RouterView />
    </main>
  </div>
</template>
