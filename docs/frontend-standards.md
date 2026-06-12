---
description: Frontend development standards for the Elevator Maintenance React/TypeScript application — component patterns, service layer, styling, and testing.
globs: ["frontend/src/**/*.{ts,tsx}", "frontend/vite.config.ts", "frontend/tsconfig.json", "frontend/package.json"]
alwaysApply: true
---

# Frontend Standards and Best Practices

## Technology Stack

| Component | Choice | Version |
|---|---|---|
| Language | TypeScript | ~6.0 |
| Framework | React | 19 |
| Build tool | Vite | 8 |
| CSS | Tailwind CSS | 4 |
| Routing | React Router | 7 |
| Charts | Recharts | 3 |
| HTTP client | fetch (native) | — |
| E2E Testing | Playwright | latest |
| Linting | ESLint + typescript-eslint | latest |

## Project Structure

```
frontend/
├── src/
│   ├── components/          # Reusable UI components (no page-specific logic)
│   │   ├── RiskBadge.tsx
│   │   ├── FeatureBar.tsx
│   │   └── ScopeTag.tsx
│   ├── pages/               # Route-level components (one per route)
│   │   ├── Dashboard.tsx
│   │   ├── ElevatorDetail.tsx
│   │   └── PostVisitReport.tsx
│   ├── services/            # API communication layer
│   │   └── elevatorService.ts
│   ├── types/               # Shared TypeScript types and interfaces
│   │   └── elevator.ts
│   ├── hooks/               # Custom React hooks (shared logic)
│   ├── utils/               # Pure utility functions (formatting, calculations)
│   ├── App.tsx              # Router setup
│   └── main.tsx             # Entry point
├── tests/
│   └── e2e/                 # Playwright E2E tests
├── playwright.config.ts
├── vite.config.ts
├── tsconfig.json
└── package.json
```

## Naming Conventions

| Element | Convention | Example |
|---|---|---|
| Component files | `PascalCase.tsx` | `RiskBadge.tsx` |
| Hook files | `camelCase.ts`, prefix `use` | `useElevatorData.ts` |
| Service files | `camelCase.ts`, suffix `Service` | `elevatorService.ts` |
| Utility files | `camelCase.ts` | `formatDate.ts` |
| Type/Interface | `PascalCase` | `ElevatorSummary` |
| CSS classes | Tailwind utilities only | `className="text-red-600 font-bold"` |
| Constants | `UPPER_SNAKE_CASE` | `API_BASE_URL` |

## Component Standards

### Functional Components Only

All components use function declarations with explicit return types.

```tsx
// Good
interface RiskBadgeProps {
  level: RiskLevel
  score: number
}

export function RiskBadge({ level, score }: RiskBadgeProps): JSX.Element {
  ...
}

// Bad
const RiskBadge = (props: any) => { ... }
```

### Component Responsibilities

- **`components/`**: Pure UI — receive props, render markup, emit events. No API calls, no routing.
- **`pages/`**: Orchestrate data fetching + compose components. One per route.
- **`hooks/`**: Extract stateful logic that is shared across multiple components.
- **`services/`**: Handle all HTTP communication. No UI logic, no React imports.

```
pages/Dashboard.tsx
  → calls useElevatorList() hook (or fetches directly for simple cases)
  → passes data to components/ElevatorTable.tsx
  → components/ElevatorTable.tsx renders rows with components/RiskBadge.tsx
```

### Props

- Always define a `Props` interface — no inline `{ prop: type }` in the function signature for components with more than two props.
- Required props first, optional props last with `?`.
- No prop drilling more than two levels deep — lift state or use context.

```tsx
interface ElevatorCardProps {
  elevator: ElevatorSummary       // required
  onSelect?: (id: string) => void // optional
}
```

## Service Layer (`src/services/`)

All API calls go through service functions — never call `fetch` directly from components or pages.

### Structure

```typescript
// src/services/elevatorService.ts

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export async function listElevators(): Promise<ElevatorSummary[]> {
  const response = await fetch(`${API_BASE}/api/elevators`)
  if (!response.ok) throw new Error(`Failed to fetch elevators: ${response.status}`)
  return response.json() as Promise<ElevatorSummary[]>
}

export async function getElevator(id: string): Promise<ElevatorDetail> {
  const response = await fetch(`${API_BASE}/api/elevators/${id}`)
  if (!response.ok) {
    if (response.status === 404) throw new Error('Elevator not found')
    throw new Error(`Failed to fetch elevator: ${response.status}`)
  }
  return response.json() as Promise<ElevatorDetail>
}

export async function submitReport(
  elevatorId: string,
  report: PostVisitReport,
): Promise<ReportResponse> {
  const response = await fetch(`${API_BASE}/api/elevators/${elevatorId}/report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(report),
  })
  if (!response.ok) throw new Error(`Failed to submit report: ${response.status}`)
  return response.json() as Promise<ReportResponse>
}
```

### Rules

- Each service function has an explicit return type.
- On non-2xx responses, throw a typed `Error` with a descriptive message.
- The API base URL comes from `VITE_API_URL` env variable — never hardcoded.
- Service functions are `async` and return `Promise<T>`.

## Types (`src/types/`)

- All shared types live in `src/types/`. No type definitions inline in component files (except local-only types).
- Use `interface` for object shapes, `type` for unions and aliases.

```typescript
// Good
export type RiskLevel = 'high' | 'medium' | 'low'

export interface ElevatorSummary {
  id: string
  building_name: string
  risk_score: number
  risk_level: RiskLevel
  in_model_scope: boolean
}

// Bad — inline type in component file
const [data, setData] = useState<{ id: string; score: number }[]>([])
```

## State Management

Use React's built-in hooks — no external state management library for now.

| Need | Solution |
|---|---|
| Local UI state | `useState` |
| Derived values | `useMemo` |
| Side effects / data fetching | `useEffect` + service call |
| Shared state across subtree | `useContext` + `useState` |
| Shared cross-component logic | Custom hook in `src/hooks/` |

### Data Fetching Pattern

```tsx
// pages/ElevatorDetail.tsx
export function ElevatorDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const [elevator, setElevator] = useState<ElevatorDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    getElevator(id)
      .then(setElevator)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) return <LoadingSpinner />
  if (error) return <ErrorMessage message={error} />
  if (!elevator) return <NotFound />
  return <ElevatorDetailView elevator={elevator} />
}
```

## Styling (Tailwind CSS 4)

- Use Tailwind utility classes exclusively — no custom CSS files except `index.css` for global resets.
- No inline `style` props for layout or color — use Tailwind classes.
- Extract repeated class combinations into a component, not a CSS class.
- Use semantic color names via Tailwind config (`text-risk-high`) rather than raw colors when possible.

```tsx
// Good
<span className="inline-flex items-center rounded-full px-2 py-1 text-xs font-medium bg-red-100 text-red-700">
  High Risk
</span>

// Bad
<span style={{ backgroundColor: '#fee2e2', color: '#b91c1c', borderRadius: '9999px' }}>
  High Risk
</span>
```

### Responsive Design

Use Tailwind's responsive prefixes. Design mobile-first.

```tsx
<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
```

## Routing (React Router 7)

- Define all routes in `App.tsx`.
- Use `useParams`, `useNavigate`, `useSearchParams` from `react-router-dom` — never manipulate `window.location`.
- Lazy-load page components with `React.lazy` + `Suspense` once the app grows beyond 3-4 pages.

```tsx
// App.tsx
import { BrowserRouter, Routes, Route } from 'react-router-dom'

export function App(): JSX.Element {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/elevators/:id" element={<ElevatorDetail />} />
        <Route path="/elevators/:id/report" element={<PostVisitReport />} />
      </Routes>
    </BrowserRouter>
  )
}
```

## Environment Variables

All environment variables must be prefixed with `VITE_` to be exposed to the browser.

```
# .env.development
VITE_API_URL=http://localhost:8000

# .env.production
VITE_API_URL=https://api.yourdomain.com
```

Access via `import.meta.env.VITE_API_URL`. Never use `process.env` in Vite projects.

## Testing Standards (Playwright E2E)

### When to Write E2E Tests

Write a Playwright test for every user-facing workflow defined in an OpenSpec scenario. Unit-level component testing is not required for this project — E2E tests cover the critical paths.

### Structure

```
tests/
└── e2e/
    ├── dashboard.spec.ts          # Dashboard listing, filters, sorting
    ├── elevator-detail.spec.ts    # Detail view, risk display, trend chart
    └── post-visit-report.spec.ts  # Form submission flow
```

### Test Conventions

```typescript
// tests/e2e/dashboard.spec.ts
import { test, expect } from '@playwright/test'

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('shows elevator list on load', async ({ page }) => {
    await expect(page.getByRole('table')).toBeVisible()
    await expect(page.getByRole('row')).toHaveCount.greaterThan(1)
  })

  test('filters by risk level', async ({ page }) => {
    await page.getByLabel('Risk level').selectOption('high')
    const rows = page.getByRole('row')
    // All visible rows should have high risk badge
    for (const row of await rows.all()) {
      await expect(row.getByTestId('risk-badge')).toHaveText('High')
    }
  })
})
```

### Rules

- Each test is independent — no shared state between tests.
- Use `data-testid` attributes on interactive and observable elements when role/label selectors are insufficient.
- Always restore any data state modified during a test.
- Tests run against the full stack (frontend + backend + DB) via Docker Compose.

### playwright.config.ts

```typescript
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  use: {
    baseURL: 'http://localhost:5173',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
  },
})
```

## Performance

- Memoize expensive computations with `useMemo`.
- Memoize callbacks passed as props with `useCallback` when the child is wrapped in `React.memo`.
- Avoid re-renders caused by object/array literals in JSX (`value={{ a: 1 }}` creates a new object each render).

```tsx
// Bad — new object on every render
<ElevatorContext.Provider value={{ elevators, setElevators }}>

// Good
const contextValue = useMemo(() => ({ elevators, setElevators }), [elevators])
<ElevatorContext.Provider value={contextValue}>
```

## TypeScript Configuration

Strict mode is required. `tsconfig.json` must include:

```json
{
  "compilerOptions": {
    "strict": true,
    "noImplicitAny": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true
  }
}
```

No `// @ts-ignore` or `// @ts-expect-error` without a comment explaining why.
