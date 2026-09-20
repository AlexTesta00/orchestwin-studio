// Trusted runner input, supplied with --init-script during controlled SETUP.
// Configuration.resolve() materializes artifact files; a dependencies report
// resolves the dependency graph without guaranteeing an offline artifact cache.
// Dependency verification stays enabled and resolution failures must propagate.
// https://docs.gradle.org/current/dsl/org.gradle.api.artifacts.Configuration.html

allprojects {
    val dependencyConfigurations = configurations
    tasks.register("orchestwinResolveDependencies") {
        group = "build setup"
        description = "Materialize every resolvable dependency configuration before offline execution."
        doLast {
            val started = System.nanoTime()
            dependencyConfigurations.filter { it.isCanBeResolved }.sortedBy { it.name }
                .forEach { configuration ->
                    val configurationStarted = System.nanoTime()
                    logger.lifecycle("Resolving ${configuration.name}")
                    val files = configuration.resolve()
                    val elapsedMillis = (System.nanoTime() - configurationStarted) / 1_000_000
                    logger.lifecycle("Resolved ${configuration.name}: ${files.size} artifact files in ${elapsedMillis} ms")
                }
            logger.lifecycle("Dependency resolution completed in ${(System.nanoTime() - started) / 1_000_000} ms")
        }
    }
}
