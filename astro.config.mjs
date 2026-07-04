import { defineConfig } from 'astro/config';

const repository = process.env.GITHUB_REPOSITORY?.split('/')[1] ?? '';
const owner = process.env.GITHUB_REPOSITORY_OWNER ?? 'SEU_USUARIO';
const isUserPage = repository === `${owner}.github.io`;

export default defineConfig({
  output: 'static',
  site: process.env.ASTRO_SITE ?? `https://${owner}.github.io`,
  base: process.env.ASTRO_BASE ?? (repository ? (isUserPage ? '/' : `/${repository}`) : '/'),
});
