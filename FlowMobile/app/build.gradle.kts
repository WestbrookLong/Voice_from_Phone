import java.util.UUID

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.westbrook.flowmobile"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.westbrook.flowmobile"
        minSdk = 28
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables {
            useSupportLibrary = true
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    buildFeatures {
        viewBinding = true
    }

    sourceSets {
        getByName("main") {
            assets.srcDir(layout.buildDirectory.dir("generated/assets"))
        }
    }
}

val generateVoskModelUuid by tasks.registering {
    val modelAssets = layout.projectDirectory.dir("src/main/assets/model-cn")
    val uuidFile = layout.buildDirectory.file("generated/assets/model-cn/uuid")

    inputs.dir(modelAssets)
    outputs.file(uuidFile)

    doLast {
        val file = uuidFile.get().asFile
        file.parentFile.mkdirs()
        file.writeText(UUID.randomUUID().toString())
    }
}

tasks.named("preBuild") {
    dependsOn(generateVoskModelUuid)
}

dependencies {
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.appcompat:appcompat:1.7.1")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("com.alphacephei:vosk-android:0.3.75@aar")
    implementation("net.java.dev.jna:jna:5.18.1@aar")
}
