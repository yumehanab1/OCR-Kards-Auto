plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

dependencies {
    // Bundled Chinese model: no network download during recognition.
    implementation("com.google.mlkit:text-recognition-chinese:16.0.1")
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.20.0")
}

val mobileBuildPython = providers.environmentVariable("KARDS_BUILD_PYTHON").orNull
    ?: providers.environmentVariable("LOCALAPPDATA").orNull?.let {
        "$it/CodexAndroidBuild/Python310/python.exe"
    }
    ?: "python3.10"
val distributionKeyStore = providers.environmentVariable("KARDS_ANDROID_KEYSTORE").orNull
val publicBuild = providers.environmentVariable("KARDS_PUBLIC_BUILD").orNull == "true"

android {
    namespace = "com.kards.mobilert"
    compileSdk = 35
    buildToolsVersion = "35.0.0"

    defaultConfig {
        applicationId = "com.kards.mobilert"
        minSdk = 30
        targetSdk = 35
        versionCode = 151
        versionName = "0.2.3"
        testInstrumentationRunner = "com.kards.mobilert.DeviceRegressionInstrumentation"
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    signingConfigs {
        if (distributionKeyStore != null) {
            create("distribution") {
                storeFile = file(distributionKeyStore)
                storePassword = providers.environmentVariable("KARDS_ANDROID_STORE_PASSWORD").get()
                keyAlias = providers.environmentVariable("KARDS_ANDROID_KEY_ALIAS").get()
                keyPassword = providers.environmentVariable("KARDS_ANDROID_KEY_PASSWORD").get()
            }
        }
    }
    buildTypes {
        getByName("release") {
            if (distributionKeyStore != null) signingConfig = signingConfigs.getByName("distribution")
        }
    }

    sourceSets.getByName("androidTest").assets.srcDir(layout.buildDirectory.dir("generated/deviceTestAssets"))

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

chaquopy {
    sourceSets {
        getByName("main") {
            if (publicBuild) {
                exclude("**/*_test.py", "deploy-refusal-fixtures/**", "deploy-verify-fixtures/**", "hq-fixtures/**")
                exclude("deploy-fixtures/blueprint-independent-*.png", "deploy-fixtures/blueprint-negative-*.png", "deploy-fixtures/green-table-*.png")
            }
        }
    }
    defaultConfig {
        // OpenCV's current Android wheel is published for CPython 3.10.
        version = "3.10"
        buildPython(mobileBuildPython)
        pip {
            install("numpy==1.26.2")
            install("opencv-python==4.5.1.48")
            install("chaquopy-libcxx==180000")
            install("chaquopy-openblas==0.2.20")
            install("chaquopy-libpng==1.6.34")
            install("chaquopy-libjpeg==1.5.3")
            install("chaquopy-libgfortran==4.9")
        }
    }
}

val verifyMobileCore by tasks.registering(Exec::class) {
    group = "verification"
    description = "Verify the embedded mobile core against the reviewed source manifest."
    val args = mutableListOf(mobileBuildPython, rootProject.file("tools/prepare_mobile_core.py").absolutePath, "--check")
    if (!rootProject.projectDir.parentFile.resolve("src/actions.py").isFile) args.add("--packaged-only")
    commandLine(args)
}

tasks.named("preBuild") {
    dependsOn(verifyMobileCore)
}
