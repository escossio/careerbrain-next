# Android — passada 09

O módulo `android/` gera exclusivamente `com.escossio.careerbrain.debug`, versão
`0.9.0-debug`. Ele injeta `CareerBrainApi`; nesta passada `FakeCareerBrainApi`
usa formatos e estados V1, sem backend, segredo, Google real ou candidatura
externa. A troca por cliente HTTP real pertence à 10.

Pré-requisitos de build controlado: JDK 21, Android SDK platform 35/build-tools
35, Gradle 8.11 e acesso ao repositório de dependências. Com ambiente isolado:

```
cd android
gradle :app:testDebugUnitTest :app:assembleDebug
adb install app/build/outputs/apk/debug/app-debug.apk
sha256sum app/build/outputs/apk/debug/app-debug.apk
```

O APK não é release, não usa keystore de produção e não deve ser publicado. A
instrumentação requer emulador/dispositivo descartável; o teste controlado de
inicialização limpa usa apenas a identidade sintética e só é executado depois de
verificar SDK, AVD, KVM, disco e memória no worker.
