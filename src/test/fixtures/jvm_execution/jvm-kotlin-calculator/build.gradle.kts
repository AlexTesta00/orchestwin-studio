plugins {
    application
    kotlin("jvm") version "2.4.10"
}

dependencies {
    testImplementation(kotlin("test-junit5"))
    testImplementation("org.junit.jupiter:junit-jupiter:5.11.4")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher:1.11.4")
}

kotlin {
    jvmToolchain(21)
}

application {
    mainClass = "org.orchestwin.calculator.MainKt"
}

tasks.test {
    useJUnitPlatform()
}
