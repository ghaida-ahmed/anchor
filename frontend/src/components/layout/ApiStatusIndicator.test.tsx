import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ApiStatusIndicator } from '@/components/layout/ApiStatusIndicator';

const mockStatus = vi.hoisted(() => ({ value: 'online' as string }));
vi.mock('@/hooks/useApiHealth', () => ({
  useApiHealth: () => mockStatus.value,
}));

/**
 * "API connected" was engineering status shown to students during normal use.
 * The health check itself is untouched — only the presentation is gone, and only
 * for the states that are not a problem.
 */
describe('the connectivity badge', () => {
  it('renders nothing when the API is reachable', () => {
    mockStatus.value = 'online';
    const { container } = render(<ApiStatusIndicator />);
    expect(container).toBeEmptyDOMElement();
    expect(document.body.textContent).not.toContain('API connected');
  });

  it('renders nothing while the first check is in flight', () => {
    mockStatus.value = 'checking';
    const { container } = render(<ApiStatusIndicator />);
    expect(container).toBeEmptyDOMElement();
    expect(document.body.textContent).not.toContain('Checking API');
  });

  it('still reports an unreachable backend, so the app is not silently dead', () => {
    mockStatus.value = 'unreachable';
    render(<ApiStatusIndicator />);
    expect(document.body.textContent).toContain('API offline');
  });

  it('never renders the removed copy in any state', () => {
    for (const value of ['online', 'checking', 'unreachable']) {
      mockStatus.value = value;
      const { container } = render(<ApiStatusIndicator />);
      expect(container.textContent).not.toContain('API connected');
      expect(container.textContent).not.toContain('Connected');
    }
  });
});
