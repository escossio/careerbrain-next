plugins { id("com.android.application"); id("org.jetbrains.kotlin.android"); id("org.jetbrains.kotlin.plugin.compose") }

android { namespace = "com.escossio.careerbrain"; compileSdk = 35
    defaultConfig { applicationId = "com.escossio.careerbrain"; minSdk = 26; targetSdk = 35; versionCode = 1; versionName = "0.9.0-dev"; testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner" }
    buildTypes { debug { applicationIdSuffix = ".debug"; versionNameSuffix = "-debug" } }
    buildFeatures { compose = true; buildConfig = true }
    val apiBaseUrl = providers.gradleProperty("careerbrainApiBaseUrl").orElse("").get()
    val googleWebClientId = providers.gradleProperty("careerbrainGoogleWebClientId").orElse("").get()
    val debugCaFile = providers.gradleProperty("careerbrainDebugCaFile").orElse("").get()
    val debugSecurityResources = layout.buildDirectory.dir("generated/res/careerbrainDebugSecurity")
    defaultConfig {
        buildConfigField("String", "CAREERBRAIN_API_BASE_URL", "\"${apiBaseUrl.replace("\\", "\\\\").replace("\"", "\\\"")}\"")
        buildConfigField("String", "CAREERBRAIN_GOOGLE_WEB_CLIENT_ID", "\"${googleWebClientId.replace("\\", "\\\\").replace("\"", "\\\"")}\"")
    }
    sourceSets.getByName("debug").res.srcDir(debugSecurityResources)
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
}

val generateCareerBrainDebugSecurity by tasks.registering {
    outputs.dir(layout.buildDirectory.dir("generated/res/careerbrainDebugSecurity"))
    doLast {
        val root = layout.buildDirectory.dir("generated/res/careerbrainDebugSecurity").get().asFile
        val xml = root.resolve("xml/careerbrain_network_security.xml")
        xml.parentFile.mkdirs()
        val apiUrl = providers.gradleProperty("careerbrainApiBaseUrl").orElse("").get()
        val caPath = providers.gradleProperty("careerbrainDebugCaFile").orElse("").get()
        if (apiUrl.isNotBlank() && caPath.isBlank()) throw GradleException("careerbrainDebugCaFile is required for a real debug endpoint")
        val extraAnchor = if (caPath.isBlank()) "" else {
            val ca = file(caPath)
            if (!ca.isFile) throw GradleException("careerbrainDebugCaFile is not a readable file")
            val raw = root.resolve("raw/careerbrain_homolog_ca.pem")
            raw.parentFile.mkdirs(); ca.copyTo(raw, overwrite = true)
            "<debug-overrides><trust-anchors><certificates src=\"@raw/careerbrain_homolog_ca\" /></trust-anchors></debug-overrides>"
        }
        xml.writeText("<network-security-config><base-config cleartextTrafficPermitted=\"false\"><trust-anchors><certificates src=\"system\" /></trust-anchors></base-config>$extraAnchor</network-security-config>")
    }
}

tasks.named("preDebugBuild").configure { dependsOn(generateCareerBrainDebugSecurity) }

kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.activity:activity-compose:1.10.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    implementation("androidx.credentials:credentials:1.5.0")
    implementation("androidx.credentials:credentials-play-services-auth:1.5.0")
    implementation("com.google.android.libraries.identity.googleid:googleid:1.1.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    debugImplementation("androidx.compose.ui:ui-tooling")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation(platform("androidx.compose:compose-bom:2024.12.01"))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    androidTestImplementation("androidx.test:core-ktx:1.6.1")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
}
