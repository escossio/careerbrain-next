# CareerBrain Next

Catálogo universal de oportunidades, perfil profissional privado e recomendações
somente de publicações elegíveis desde a criação da conta. Cliente Android com Google OIDC.

Este candidato contém a fundação da passada 01: contratos, decisões, governança e
testes de conformidade offline. API, banco, fila, IA real e APK pertencem às passadas
seguintes, mediante autorização individual. Não há implantação certificada aqui.

- [Estado](ESTADO_DA_EXECUCAO.md) e [status](STATUS.md).
- [Plano das dez passadas](PLANO_DE_EXECUCAO.md).
- [Decisões arquiteturais](DECISOES_ARQUITETURAIS.md).
- [Contratos V1](contracts/README.md).
- [Arquitetura](docs/architecture.md), [CI](docs/ci.md) e [gates](docs/gates.md).
- [Política de publicação](docs/publication.md) e [evidências do candidato](docs/evidence-01.md).

## Verificação curta

Python 3.13. Crie um ambiente virtual fora desta árvore, instale as dependências
fixadas em `requirements-ci.txt` com `pip --isolated install --only-binary=:all:
--require-hashes -r requirements-ci.txt` e, nesta raiz, execute:

```sh
python -m tools.verify
python -m tools.repository_policy --candidate
```

A instalação baixa dependências; as verificações usam apenas dados locais. Testes
bloqueiam sockets e subprocessos. Não iniciam banco, API ou chamadas de provedor.
No checkout Git futuro, a política também inspeciona todos os blobs alcançáveis.

A lista `public-allowlist.json` admite somente os arquivos revisados. Publicação,
proteção de main, execução remota do CI e merge dependem de aprovação posterior.
Este candidato não inclui histórico Git, PRs, logs anteriores ou metadados operacionais.
Uma licença de distribuição ainda deve ser escolhida pelo titular; nenhuma licença
foi acrescentada por inferência da intenção de tornar o código público.
