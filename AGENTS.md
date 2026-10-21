# CareerBrain Next — regras permanentes

- Leia STATUS.md e ESTADO_DA_EXECUCAO.md antes de agir.
- Execute somente a passada nominal autorizada e pare ao concluir.
- Preserve projetos existentes e serviços compartilhados.
- Use fixtures sintéticas; credenciais, dados pessoais e inventários operacionais ficam fora do Git.
- Antes de editar, leia o arquivo; mantenha mudanças pequenas e reversíveis.
- Atualize STATUS.md e ESTADO_DA_EXECUCAO.md por marcos significativos.
- Use branch isolada e PR. Merge depende de autorização e dos checks obrigatórios.
- No control plane, apenas inspeção, lint e testes curtos. PostgreSQL, migrações e suítes pesadas somente em workers distribuídos dedicados. Pool indisponível bloqueia o gate, sem fallback local.
- Não altere mecanismos de CI ou serviços de outros projetos.
- Produção, credenciais, tráfego faturável e assinatura têm gates específicos.
- Publicação exige revisão por arquivo, lista de permissões e histórico inicial novo. Scanners não substituem revisão de conteúdo e aprovação humana.
