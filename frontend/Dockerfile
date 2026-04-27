FROM node:20-alpine AS build

WORKDIR /app

RUN corepack enable

COPY package.json ./

RUN corepack prepare pnpm@9.12.3 --activate \
 && pnpm add -D vite@5.4.3 @vitejs/plugin-react@4.3.1 typescript@5.5.3 \
 && pnpm install

COPY . .

RUN pnpm exec vite build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 5173

CMD ["nginx", "-g", "daemon off;"]