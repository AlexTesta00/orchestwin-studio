plugins {
    application
    kotlin("jvm") version "2.4.10"
}

repositories {
    mavenCentral()
}

dependencies {
    testImplementation(kotlin("test"))
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
