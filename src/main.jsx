import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import AppErrorBoundary from './components/AppErrorBoundary.jsx';
import './styles/playerTheme.css';
import './styles.css';
import './styles/metadataAuthority.css';
import './styles/identityReview.css';
import './styles/metadataCorrection.css';
import './styles/posterEditor.css';
import './styles/smartMatch.css';
import './components/movie-card/movieCard.css';

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </StrictMode>
);
