# Android — passada 09

O módulo `android/` gera exclusivamente `com.escossio.careerbrain.debug`, versão
`0.9.0-debug`. Ele injeta `CareerBrainApi`; nesta passada `FakeCareerBrainApi`
usa formatos e estados V1, sem backend, segredo, Google real ou candidatura
externa. A troca por cliente HTTP real pertence à 10.

Pré-requisitos de build controlado: JDK 21, Android SDK platform 35/build-tools
35, Gradle 8.11 e acesso ao repositório de dependências. Com ambiente isolado:

```
cd android
gradle :app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest
adb install app/build/outputs/apk/debug/app-debug.apk
adb install app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
sha256sum app/build/outputs/apk/debug/app-debug.apk
```

O APK não é release, não usa keystore de produção e não deve ser publicado. A
instrumentação requer emulador/dispositivo descartável; os testes usam somente
identidade e vagas sintéticas para entrada, segunda página, salvar, sincronizar e
limpeza. Ela só é executada depois de verificar SDK, AVD, KVM, disco e memória no
worker.

O botão **Sincronizar** percorre páginas do fake de mudanças, mantém o
high-watermark enquanto há páginas e faz ACK antes de persistir o próximo cursor.
Falha HTTP ou offline não avança o cursor; `REMOVED` elimina somente a vaga local.
O único dado persistido é esse cursor opaco, em preferências criptografadas e com
backup do app desabilitado. Sessão, token, senha e PII não são persistidos; uma
reinstalação começa sem sessão e faz bootstrap ao entrar novamente.

O seletor de PDF lê no máximo 5 MiB e consulta apenas um byte adicional para
rejeitar excesso, sem reter um documento maior em memória. O contrato fake de
upload continua aceitando somente PDF de até 5 MiB.
