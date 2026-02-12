FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .
ENV VITE_API_URL=/api
RUN npm run build

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host"]
