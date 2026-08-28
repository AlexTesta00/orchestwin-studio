ThisBuild / scalaVersion := "3.3.8"
ThisBuild / organization := "org.orchestwin"
ThisBuild / version := "1.0.0"

Compile / mainClass := Some("org.orchestwin.greeting.Main")

libraryDependencies += "org.scalameta" %% "munit" % "1.0.2" % Test
