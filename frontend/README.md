# Kolya BR Proxy -- Frontend

Web admin dashboard built with Quasar Framework (Vue 3 + TypeScript).

## Tech Stack

- **Framework**: Quasar Framework (Vue 3 + Vite)
- **Language**: TypeScript
- **State Management**: Pinia
- **HTTP Client**: Axios

## Quick Start

```bash
# Install dependencies
npm install

# Configure environment
cp .env.example .env.local
# Edit .env.local: set VITE_API_BASE_URL and redirect URIs

# Start development server
npm run dev
```

Visit `http://localhost:9000`.

## Project Structure

```
src/
├── boot/            # Startup files (axios, pinia)
├── components/      # Reusable components
├── layouts/         # Layout components
├── pages/           # Page components
│   ├── LoginPage.vue / RegisterPage.vue
│   ├── DashboardPage.vue
│   ├── TokensPage.vue / ModelsPage.vue
│   ├── PlaygroundPage.vue    # AI chat testing
│   └── SettingsPage.vue
├── router/          # Route configuration
├── stores/          # Pinia stores (auth, tokens, models)
└── utils/           # API utilities
```

## Key Features

- User authentication (JWT + Microsoft OAuth + Cognito OAuth)
- API token management with quota and expiration
- Model configuration (dynamic from AWS Bedrock)
- AI Playground with streaming chat
- Usage statistics dashboard

## Documentation

- **[Architecture](../docs/architecture.md)** -- system design and component overview
- **[API Reference](../docs/api-reference.md)** -- backend API documentation
- **[Deployment](../docs/deployment.md)** -- production deployment guide
