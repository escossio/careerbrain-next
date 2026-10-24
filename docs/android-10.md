# Android — integração da passada 10

O APK debug mantém `FakeCareerBrainApi` quando não há configuração de build. Para
homologação autorizada, o pipeline pode fornecer somente estas propriedades Gradle:

```
-PcareerbrainApiBaseUrl=<URL_HTTPS_APROVADA>
-PcareerbrainGoogleWebClientId=<CLIENT_ID_PUBLICO_APROVADO>
```

Elas não têm valor padrão no repositório e não devem ser registradas em logs,
artefatos públicos ou `gradle.properties`. O client ID é público; segredo OAuth,
token, tenant, usuário e papel não entram no APK nem são parâmetros do app.

`HttpCareerBrainApi` aceita somente URL HTTPS sem credenciais, query ou fragmento,
desabilita cleartext e redirects, aplica connect timeout de 10 s/read timeout de
20 s e trata falha de transporte separadamente de HTTP. Um 401 pode disparar uma
única rotação e reenvio somente de uma operação com chave de idempotência. Cursores
continuam opacos e persistem apenas após ACK. Erros 401/403/409/429/5xx são
devolvidos à interface sem avançar estado local.

O botão Google, quando configurado, primeiro obtém o challenge da API e então usa
Credential Manager/Google Identity com o nonce retornado. O backend continua sendo
o único responsável por validar assinatura, audiência, `azp`, emissor e sessão.
O fluxo não foi executado contra uma conta Google real nesta etapa.

O upload usa multipart limitado pelo seletor existente; candidatura é um registro
manual idempotente. TTS possui fronteira HTTP contratual e fica indisponível de
forma silenciosa enquanto G-TTS não estiver aprovado. Esta documentação não prova
HTTPS, consentimento, Google real, TTS real ou rede móvel; tais provas permanecem
nos gates externos da passada 10.
